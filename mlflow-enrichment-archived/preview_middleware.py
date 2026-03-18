"""Lightweight middleware to capture LLM request/response previews for MLflow UI.

This middleware captures the actual prompt and completion content from HTTP
request/response bodies and writes them to MLflow's trace_info table.

Why this is needed:
- OpenTelemetry instrumentation does NOT capture large content in span attributes
- MLflow's request_preview/response_preview columns require actual LLM content
- The enrichment service cannot extract this data from OTLP traces

What this middleware does NOT do:
- Does NOT write to trace_tags (enrichment service handles that)
- Does NOT create spans (OpenTelemetry auto-instrumentation handles that)
- Does NOT set MLflow experiments or tracking URIs
- Does NOT duplicate enrichment logic

This is a minimal solution focused solely on populating preview fields.
"""
import json
import os
import logging
import psycopg2
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.background import BackgroundTask
from opentelemetry import trace as otel_trace

logger = logging.getLogger(__name__)


class PreviewCaptureMiddleware(BaseHTTPMiddleware):
    """Captures request/response bodies and writes to trace_info for MLflow UI preview."""

    async def dispatch(self, request: Request, call_next):
        # Only capture LLM inference endpoints
        if not request.url.path.startswith(("/v1/chat/completions", "/v1/embeddings")):
            return await call_next(request)

        # Read and cache request body
        body = await request.body()
        try:
            request_data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            request_data = {}

        # Get trace ID from current OpenTelemetry span context
        otel_span = otel_trace.get_current_span()
        trace_id = f"tr-{otel_span.get_span_context().trace_id:032x}"

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
            response_data = {}

        # Background task to write previews to database
        def write_previews():
            import time

            db_password = os.getenv("POSTGRES_PASSWORD")
            if not db_password:
                logger.warning(f"[Preview] POSTGRES_PASSWORD not set for trace {trace_id}")
                return

            # Extract previews from request/response
            request_preview = ""
            messages = request_data.get("messages", [])
            if messages and isinstance(messages, list):
                # Get last user message
                for msg in reversed(messages):
                    if isinstance(msg, dict) and msg.get("role") == "user":
                        request_preview = msg.get("content", "")[:1000]
                        break

            response_preview = ""
            if response_data and isinstance(response_data, dict):
                choices = response_data.get("choices", [])
                if choices and isinstance(choices, list):
                    first_choice = choices[0]
                    if isinstance(first_choice, dict):
                        message = first_choice.get("message", {})
                        if isinstance(message, dict):
                            response_preview = message.get("content", "")[:1000]

            # Wait for trace to exist in database (MLflow writes via OTLP endpoint)
            max_retries = 10
            for attempt in range(max_retries):
                time.sleep(0.5)  # 500ms between attempts

                try:
                    conn = psycopg2.connect(
                        host=os.getenv("POSTGRES_HOST", "pgvector-cluster-rw.catalystlab-shared.svc.cluster.local"),
                        port=os.getenv("POSTGRES_PORT", "5432"),
                        dbname="mlflow",
                        user=os.getenv("POSTGRES_USER", "postgres"),
                        password=db_password
                    )
                    cur = conn.cursor()

                    # Check if trace exists
                    cur.execute("SELECT 1 FROM trace_info WHERE request_id = %s", (trace_id,))
                    if cur.fetchone():
                        # Update only the preview fields (do NOT touch tags/metadata)
                        cur.execute(
                            """
                            UPDATE trace_info
                            SET request_preview = COALESCE(request_preview, %s),
                                response_preview = COALESCE(response_preview, %s)
                            WHERE request_id = %s
                            """,
                            (request_preview, response_preview, trace_id)
                        )
                        conn.commit()
                        cur.close()
                        conn.close()
                        logger.info(f"[Preview] Updated previews for trace {trace_id}")
                        return

                    # Trace doesn't exist yet, retry
                    cur.close()
                    conn.close()

                except Exception as e:
                    logger.debug(f"[Preview] Attempt {attempt+1} for {trace_id}: {e}")
                    continue

            logger.warning(f"[Preview] Trace {trace_id} not found after {max_retries} attempts")

        # Return response with background task
        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
            background=BackgroundTask(write_previews)
        )
