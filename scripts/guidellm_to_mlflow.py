#!/usr/bin/env python3
"""
GuideLLM to MLflow Integration Script

Parses a GuideLLM JSON report and logs the benchmark metrics to MLflow.
Designed to be run as a post-processing step in the GuideLLM Kubernetes Job.

Usage:
  export MLFLOW_TRACKING_URI="http://mlflow.catalystlab-shared.svc.cluster.local:5000"
  uv run guidellm_to_mlflow.py <path-to-guidellm-report.json> [--experiment-name <name>]
"""

import sys
import json
import argparse
import os
import glob

def parse_args():
    parser = argparse.ArgumentParser(description="Upload GuideLLM JSON reports to MLflow")
    parser.add_argument("report_path", help="Path to GuideLLM JSON report (or directory containing reports)")
    parser.add_argument("--experiment-name", default="guidellm-benchmarks", help="MLflow experiment name")
    parser.add_argument("--run-name", help="Optional custom name for the MLflow run")
    return parser.parse_args()

def check_mlflow_available():
    try:
        import mlflow
        return True
    except ImportError:
        print("Error: mlflow Python package is not installed.")
        print("Please install it: uv pip install mlflow")
        sys.exit(1)

def process_report(filepath, experiment_name, run_name=None):
    import mlflow

    print(f"Processing {filepath}...")
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Failed to read JSON: {e}")
        return False

    # Create or set experiment
    mlflow.set_experiment(experiment_name)

    # Start a new run
    with mlflow.start_run(run_name=run_name or os.path.basename(filepath)):
        # Log basic configuration as params
        params = {}
        if "backend" in data:
            params["backend"] = data["backend"]
        if "target" in data:
            params["target"] = data["target"]
        if "model" in data:
            params["model"] = data["model"]

        # Add concurrency info if available
        if "concurrency" in data:
            params["concurrency_level"] = data["concurrency"]

        mlflow.log_params(params)

        # Log metrics (throughput, latency, TTFT, ITL)
        metrics = {}

        # GuideLLM JSON structure varies by version, trying common paths
        # Look for summary stats
        if "summary" in data:
            summary = data["summary"]
            # Throughput
            if "req_per_sec" in summary:
                metrics["throughput_req_per_sec"] = summary["req_per_sec"]
            if "tok_per_sec" in summary:
                metrics["throughput_tok_per_sec"] = summary["tok_per_sec"]

            # Latency (Time To First Token)
            if "ttft_ms" in summary:
                if isinstance(summary["ttft_ms"], dict) and "p99" in summary["ttft_ms"]:
                    metrics["ttft_p99_ms"] = summary["ttft_ms"]["p99"]
                    metrics["ttft_p50_ms"] = summary["ttft_ms"]["p50"]
                    metrics["ttft_mean_ms"] = summary["ttft_ms"]["mean"]
                elif isinstance(summary["ttft_ms"], (int, float)):
                    metrics["ttft_mean_ms"] = summary["ttft_ms"]

            # Inter-Token Latency
            if "itl_ms" in summary:
                if isinstance(summary["itl_ms"], dict) and "p99" in summary["itl_ms"]:
                    metrics["itl_p99_ms"] = summary["itl_ms"]["p99"]
                    metrics["itl_p50_ms"] = summary["itl_ms"]["p50"]
                    metrics["itl_mean_ms"] = summary["itl_ms"]["mean"]
                elif isinstance(summary["itl_ms"], (int, float)):
                    metrics["itl_mean_ms"] = summary["itl_ms"]

            # E2E Latency
            if "e2e_ms" in summary:
                if isinstance(summary["e2e_ms"], dict) and "p99" in summary["e2e_ms"]:
                    metrics["e2e_latency_p99_ms"] = summary["e2e_ms"]["p99"]
                    metrics["e2e_latency_mean_ms"] = summary["e2e_ms"]["mean"]

        # Alternative structure (e.g. from some versions of vllm-project/guidellm)
        elif "results" in data:
            results = data["results"]
            if "throughput" in results:
                metrics["throughput_req_per_sec"] = results["throughput"].get("requests_per_second", 0)
                metrics["throughput_tok_per_sec"] = results["throughput"].get("tokens_per_second", 0)
            if "latency" in results:
                lat = results["latency"]
                if "ttft" in lat:
                    metrics["ttft_mean_ms"] = lat["ttft"].get("mean", 0)
                    metrics["ttft_p99_ms"] = lat["ttft"].get("p99", 0)
                if "tpot" in lat or "itl" in lat:
                    itl_key = "tpot" if "tpot" in lat else "itl"
                    metrics["itl_mean_ms"] = lat[itl_key].get("mean", 0)
                    metrics["itl_p99_ms"] = lat[itl_key].get("p99", 0)

        if metrics:
            mlflow.log_metrics(metrics)
            print(f"Logged {len(metrics)} metrics to MLflow.")
        else:
            print("Warning: Could not find recognizable metrics in the JSON structure.")

        # Log the raw JSON file as an artifact for deep dives
        mlflow.log_artifact(filepath, artifact_path="raw_reports")
        print(f"Logged raw report as artifact.")

    return True

def main():
    args = parse_args()
    check_mlflow_available()

    if not os.environ.get("MLFLOW_TRACKING_URI"):
        print("Warning: MLFLOW_TRACKING_URI is not set. Defaulting to local ./mlruns")

    if os.path.isdir(args.report_path):
        # Process all JSON files in directory
        files = glob.glob(os.path.join(args.report_path, "*.json"))
        if not files:
            print(f"No JSON files found in {args.report_path}")
            sys.exit(1)

        success_count = 0
        for f in files:
            if process_report(f, args.experiment_name):
                success_count += 1
        print(f"Successfully processed {success_count}/{len(files)} reports.")
    else:
        # Process single file
        if not os.path.exists(args.report_path):
            print(f"Error: File not found: {args.report_path}")
            sys.exit(1)
        process_report(args.report_path, args.experiment_name, args.run_name)

if __name__ == "__main__":
    main()
