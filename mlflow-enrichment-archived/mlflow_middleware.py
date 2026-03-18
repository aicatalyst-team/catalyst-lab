"""MLflow tracing middleware for LlamaStack FastAPI app.

This middleware intercepts LLM inference requests and wraps them with MLflow's
Python SDK to populate MLflow UI fields (Request, Response, Session, User, etc.)
that OpenTelemetry auto-instrumentation alone cannot fill.

Deployed via Containerfile injection into the llamastack-starter image.
Compatible with MLflow 3.x API using fluent API.
"""
import mlflow
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.background import BackgroundTask
import json
import os
import logging
import psycopg2


class MLflowTracingMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that creates MLflow traces for inference requests."""

    def __init__(self, app):
        super().__init__(app)
        # Configure MLflow from environment or use cluster service
        tracking_uri = os.getenv(
            "MLFLOW_TRACKING_URI",
            "http://mlflow.catalystlab-shared.svc.cluster.local:5000"
        )
        mlflow.set_tracking_uri(tracking_uri)

        # Use experiment ID from environment or default to llamastack-traces
        experiment_name = os.getenv("MLFLOW_EXPERIMENT_NAME", "llamastack-traces")
        mlflow.set_experiment(experiment_name)

        # Enable MLflow tracing
        mlflow.tracing.enable()

    async def dispatch(self, request: Request, call_next):
        # Only trace LLM inference endpoints, skip health checks and static assets
        if not request.url.path.startswith(("/v1/chat/completions", "/v1/embeddings", "/v1/agents")):
            return await call_next(request)

        # Read request body once and cache for downstream processing
        body = await request.body()
        try:
            request_data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            request_data = {}

        # Extract request metadata for MLflow trace
        model = request_data.get("model", "unknown")
        messages = request_data.get("messages", [])

        # Determine trace name from endpoint and model
        if "chat" in request.url.path:
            span_name = f"chat {model}"
        elif "embedding" in request.url.path:
            span_name = f"embedding {model}"
        elif "agent" in request.url.path:
            span_name = f"agent {request_data.get('agent_id', 'unknown')}"
        else:
            span_name = f"{request.method} {request.url.path}"

        # Extract user and session IDs from headers (or use defaults)
        user_id = request.headers.get("X-User-ID", "system")
        session_id = request.headers.get("X-Session-ID", "llamastack-default")

        logger = logging.getLogger(__name__)

        # Create span with inputs/outputs
        # Note: We create a span within the OpenTelemetry-created root trace
        with mlflow.start_span(name=span_name) as span:
            # Get the trace ID from the span context to add trace-level metadata
            from opentelemetry import trace as otel_trace
            otel_span = otel_trace.get_current_span()
            trace_id = f"tr-{otel_span.get_span_context().trace_id:032x}"
            logger.info(f"[MLflow] Working with trace ID: {trace_id}")
            try:
                # Set span attributes
                span.set_attribute("model", model)
                span.set_attribute("user_id", user_id)
                span.set_attribute("session_id", session_id)
                span.set_attribute("version", model.split("/")[-1] if "/" in model else model)

                # Set inputs
                span.set_inputs({"model": model, "messages": messages})

                # Reconstruct request with cached body
                async def receive():
                    return {"type": "http.request", "body": body}

                modified_request = Request(request.scope, receive)

                # Process request
                response = await call_next(modified_request)

                # Capture response body
                response_body = b""
                async for chunk in response.body_iterator:
                    response_body += chunk

                # Parse response JSON
                try:
                    response_data = json.loads(response_body)
                except json.JSONDecodeError:
                    response_data = {"raw": response_body.decode("utf-8", errors="replace")}

                # Set outputs
                span.set_outputs(response_data)

                if response.status_code >= 400:
                    span.set_status("ERROR")
                else:
                    span.set_status("OK")

            except Exception as e:
                span.set_status("ERROR")
                span.set_attribute("error.message", str(e))
                raise

            # Background task to write trace metadata to database
            def write_trace_metadata():
                import time

                # Use the same PostgreSQL password already configured for LlamaStack
                db_password = os.getenv("POSTGRES_PASSWORD")
                if not db_password:
                    logger.warning("[MLflow] POSTGRES_PASSWORD not found in environment")
                    return

                # Wait for trace to be written to database with retry logic
                max_retries = 10
                for attempt in range(max_retries):
                    time.sleep(0.5)  # Wait 500ms between attempts

                    try:
                        # Connect and check if trace exists
                        conn = psycopg2.connect(
                            host=os.getenv("POSTGRES_HOST", "pgvector-cluster-rw"),
                            port=os.getenv("POSTGRES_PORT", "5432"),
                            dbname="mlflow",
                            user=os.getenv("POSTGRES_USER", "postgres"),
                            password=db_password
                        )
                        cur = conn.cursor()

                        # Check if trace exists
                        cur.execute("SELECT 1 FROM trace_info WHERE request_id = %s", (trace_id,))
                        if cur.fetchone():
                            # Trace exists, insert metadata into BOTH tables
                            # trace_tags: Used by MLflow UI for display columns
                            # trace_request_metadata: Additional metadata storage

                            # Extract model version and source from model string
                            # Model format: "vllm/RedHatAI/Qwen3-Next-80B-A3B-Instruct-FP8"  # pragma: allowlist secret
                            version_value = model.split("/")[-1] if "/" in model else model
                            source_value = "vllm" if "vllm/" in model else "llamastack"

                            # Extract tokens from response usage
                            prompt_tokens = ""
                            completion_tokens = ""
                            total_tokens = ""
                            tokens_value = ""
                            if response_data and isinstance(response_data, dict):
                                usage = response_data.get("usage", {})
                                if usage:
                                    prompt_tokens = str(usage.get("prompt_tokens", ""))
                                    completion_tokens = str(usage.get("completion_tokens", ""))
                                    total_tokens = str(usage.get("total_tokens", ""))
                                    if prompt_tokens and completion_tokens:
                                        tokens_value = f"{prompt_tokens}/{completion_tokens}"

                            # Write to trace_tags (UI reads from here)
                            tag_entries = [
                                ("mlflow.user", user_id),
                                ("user.id", user_id),
                                ("mlflow.session", session_id),
                                ("session.id", session_id),
                                ("mlflow.traceName", span_name),
                                ("version", version_value),
                                ("mlflow.version", version_value),
                                ("source", source_value),
                                ("mlflow.source.name", source_value),
                                ("mlflow.source.type", "GENAI"),
                            ]

                            # Add token tags if available
                            if prompt_tokens:
                                tag_entries.append(("mlflow.promptTokens", prompt_tokens))
                            if completion_tokens:
                                tag_entries.append(("mlflow.completionTokens", completion_tokens))
                            if total_tokens:
                                tag_entries.append(("mlflow.totalTokens", total_tokens))
                            if tokens_value:
                                tag_entries.append(("tokens", tokens_value))

                            for key, value in tag_entries:
                                cur.execute(
                                    """
                                    INSERT INTO trace_tags (key, value, request_id)
                                    VALUES (%s, %s, %s)
                                    ON CONFLICT (key, request_id) DO UPDATE SET value = EXCLUDED.value
                                    """,
                                    (key, value, trace_id)
                                )

                            # Also write to trace_request_metadata for completeness
                            metadata_entries = [
                                ("mlflow.trace.user", user_id),
                                ("mlflow.trace.session", session_id),
                                ("mlflow.trace.name", span_name),
                                ("mlflow.trace.version", model.split("/")[-1] if "/" in model else model)
                            ]

                            for key, value in metadata_entries:
                                cur.execute(
                                    """
                                    INSERT INTO trace_request_metadata (key, value, request_id)
                                    VALUES (%s, %s, %s)
                                    ON CONFLICT (key, request_id) DO UPDATE SET value = EXCLUDED.value
                                    """,
                                    (key, value, trace_id)
                                )

                            # Update trace_info with request/response previews for MLflow UI
                            # Extract last user message as request preview
                            request_preview = ""
                            if messages and isinstance(messages, list):
                                for msg in reversed(messages):
                                    if isinstance(msg, dict) and msg.get("role") == "user":
                                        request_preview = msg.get("content", "")[:1000]
                                        break

                            # Extract assistant response as response preview
                            response_preview = ""
                            if response_data and isinstance(response_data, dict):
                                choices = response_data.get("choices", [])
                                if choices and isinstance(choices, list):
                                    first_choice = choices[0]
                                    if isinstance(first_choice, dict):
                                        message = first_choice.get("message", {})
                                        if isinstance(message, dict):
                                            response_preview = message.get("content", "")[:1000]

                            # Update trace_info table
                            cur.execute(
                                """
                                UPDATE trace_info
                                SET request_preview = %s, response_preview = %s
                                WHERE request_id = %s
                                """,
                                (request_preview, response_preview, trace_id)
                            )

                            conn.commit()
                            cur.close()
                            conn.close()
                            logger.info(f"[MLflow] Successfully wrote trace metadata for {trace_id}")
                            return
                        else:
                            # Trace doesn't exist yet, retry
                            cur.close()
                            conn.close()
                            if attempt == max_retries - 1:
                                logger.warning(f"[MLflow] Trace {trace_id} not found after {max_retries} attempts")
                                return
                            continue

                    except Exception as e:
                        logger.warning(f"[MLflow] Attempt {attempt+1} failed: {e}")
                        if attempt == max_retries - 1:
                            logger.warning(f"[MLflow] Failed to write trace metadata after {max_retries} attempts: {e}")
                        continue

            # Return response with background task
            return Response(
                content=response_body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
                background=BackgroundTask(write_trace_metadata)
            )
