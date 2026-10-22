"""
tools/run_model_discovery.py
============================
Executable script to run live authenticated model discovery and output readable inventory.
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.model_discovery import get_model_discovery_engine


def main():
    print("=" * 70)
    print("FRIDAY AI: LIVE AUTHENTICATED MODEL DISCOVERY")
    print("=" * 70)

    engine = get_model_discovery_engine()
    catalog = engine.discover_all_credentials(force_refresh=True)

    print("\n--- DISCOVERY METADATA ---")
    print(f"Generated at: {catalog['metadata']['generated_at']}")
    print(f"Catalog file: {engine.catalog_path}")
    print(f"Search tool providers (not LLMs): {catalog['metadata']['search_tool_providers']}")
    print(f"Explicitly excluded local providers: {catalog['metadata']['excluded_local_providers']}")

    print("\n--- PROVIDER SUMMARY ---")
    for prov, meta in catalog["providers"].items():
        models = catalog["models_by_provider"].get(prov, [])
        key_count = meta["configured_keys_count"]
        fps = ", ".join(meta["key_fingerprints"]) if meta["key_fingerprints"] else "none"
        print(f"Provider: {prov:12} | Keys: {key_count} (FP: {fps}) | Discovered Models: {len(models)}")

    print(f"\nTotal compatible models across all providers: {len(catalog['all_compatible_models'])}")

    print("\n--- SAMPLE MODELS BY PROVIDER ---")
    for prov, models in catalog["models_by_provider"].items():
        print(f"\n[{prov.upper()}] ({len(models)} models)")
        for m in models[:6]:
            print(f"  - {m['id']} (ctx: {m['context_window']}, caps: {', '.join(m['capabilities'])})")
        if len(models) > 6:
            print(f"    ... and {len(models) - 6} more models.")

    if catalog["discovery_failures"]:
        print("\n--- DISCOVERY FAILURES ---")
        for f in catalog["discovery_failures"]:
            print(f"  Provider: {f['provider']}, Ref: {f['key_reference']}, Error: {f['error']}")
    else:
        print("\nAll configured keys discovered with ZERO errors!")


if __name__ == "__main__":
    main()
