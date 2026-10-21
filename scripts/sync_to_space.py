"""
scripts/sync_to_space.py
Synchronizes the local Space bundle (space/) to Hugging Face Spaces using HfApi.upload_folder.
Reads HF_TOKEN and SPACE_ID strictly from the environment.
Failures are logged safely without exposing secrets.
"""
import os
import sys
import logging
from pathlib import Path
from huggingface_hub import HfApi

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("sync_to_space")


def sync_space(bundle_dir: str = "space", space_id: str = None, token: str = None) -> bool:
    """
    Syncs bundle_dir to the specified Hugging Face Space.
    Returns True on success, False on failure or if credentials missing.
    Never prints or logs the token.
    """
    try:
        from huggingface_hub import get_token
        token = token or os.environ.get("HF_TOKEN") or get_token()
    except Exception:
        token = token or os.environ.get("HF_TOKEN")
    space_id = space_id or os.environ.get("SPACE_ID") or "hasanshahir/lahore-air-quality-decision-system"

    if not token or not space_id:
        logger.info(
            "Hugging Face Space sync skipped: HF_TOKEN and/or SPACE_ID environment variables are not set."
        )
        return False

    bundle_path = Path(bundle_dir)
    if not bundle_path.exists() or not (bundle_path / "app.py").exists():
        logger.info(f"Bundle directory '{bundle_dir}' not found or incomplete. Building space bundle...")
        try:
            from scripts.build_space_bundle import build_space_bundle
            build_space_bundle(bundle_path)
        except Exception as e:
            logger.error(f"Failed to build Space bundle: {e}")
            return False

    logger.info(f"Uploading Space bundle '{bundle_path.as_posix()}' to Hugging Face Space: '{space_id}'...")
    try:
        api = HfApi(token=token)
        api.upload_folder(
            folder_path=str(bundle_path),
            repo_id=space_id,
            repo_type="space",
            commit_message="Hourly sync from automated HackInsight pipeline",
        )
        logger.info(f"Successfully uploaded bundle to Hugging Face Space: https://huggingface.co/spaces/{space_id}")
        return True
    except Exception as e:
        logger.error(f"Hugging Face Space upload failed: {e}")
        return False


if __name__ == "__main__":
    env_token = os.environ.get("HF_TOKEN")
    env_space_id = os.environ.get("SPACE_ID")

    if not env_token or not env_space_id:
        print("\n=======================================================")
        print(" Hugging Face Space Sync Script")
        print("=======================================================")
        print("To sync your dashboard to Hugging Face Spaces, ensure the following:")
        print("  1. Create a Streamlit Space on https://huggingface.co/new-space")
        print("  2. Create a Write access token at https://huggingface.co/settings/tokens")
        print("  3. Set environment variables in your terminal session:")
        print("     $env:HF_TOKEN=\"hf_yourWriteToken\"")
        print("     $env:SPACE_ID=\"your-username/your-space-name\"")
        print("  4. Re-run: python scripts/sync_to_space.py")
        print("=======================================================\n")
        sys.exit(0)

    success = sync_space(space_id=env_space_id, token=env_token)
    sys.exit(0 if success else 1)
