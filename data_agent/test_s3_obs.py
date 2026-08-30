"""Optional Huawei OBS S3-compatibility integration test.

The test must not perform network or credential checks during module import:
pytest collection should remain usable on developer machines and in CI where
the external OBS account is intentionally absent.  When credentials are
configured, the test performs the real bucket calls and reports connection
errors as test failures.
"""

import os

import boto3
import pytest
from dotenv import load_dotenv

load_dotenv()


def test_huawei_obs_s3_compatibility() -> None:
    ak = os.getenv("HUAWEI_OBS_AK")
    sk = os.getenv("HUAWEI_OBS_SK")
    server = os.getenv("HUAWEI_OBS_SERVER")
    bucket = os.getenv("HUAWEI_OBS_BUCKET")
    placeholder_values = {"", "your_access_key_here", "your_secret_key_here"}
    if (
        not ak
        or not sk
        or ak in placeholder_values
        or sk in placeholder_values
        or not server
        or not bucket
    ):
        pytest.skip("Huawei OBS integration credentials and endpoint are not configured")

    s3_client = boto3.client(
        "s3",
        aws_access_key_id=ak,
        aws_secret_access_key=sk,
        endpoint_url=server,
        region_name="cn-north-4",
    )
    s3_client.head_bucket(Bucket=bucket)
    response = s3_client.list_objects_v2(Bucket=bucket, MaxKeys=5)
    assert isinstance(response, dict)
