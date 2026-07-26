import os

from dotenv import load_dotenv


def main() -> int:
    load_dotenv(r"D:\adk\data_agent\.env")

    ak = os.getenv("HUAWEI_OBS_AK")
    sk = os.getenv("HUAWEI_OBS_SK")
    server = os.getenv("HUAWEI_OBS_SERVER")
    bucket = os.getenv("HUAWEI_OBS_BUCKET")

    print(f"Endpoint: {server}")
    print(f"Bucket: {bucket}")
    print(f"AK loaded: {'Yes' if ak and ak != 'your_access_key_here' else 'No'}")
    print(f"SK loaded: {'Yes' if sk and sk != 'your_secret_key_here' else 'No'}")

    if not ak or ak == "your_access_key_here":
        print("Please set the actual AK/SK in .env")
        return 1

    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=ak,
            aws_secret_access_key=sk,
            endpoint_url=server,
            region_name="cn-north-4",
        )

        print()
        print(f"Attempting to access bucket '{bucket}' using boto3 (native S3 API)...")
        s3_client.head_bucket(Bucket=bucket)
        print("Bucket verified successfully!")

        response = s3_client.list_objects_v2(Bucket=bucket, MaxKeys=5)

        print()
        print("SUCCESS! Huawei Cloud OBS is fully compatible with the native S3 API via boto3.")
        if "Contents" in response:
            print("Found the following objects in the bucket:")
            for obj in response["Contents"]:
                print(f" - {obj['Key']} ({obj['Size']} bytes)")
        else:
            print("The bucket is currently empty, but the S3 connection was successful.")
    except (BotoCoreError, ClientError) as exc:
        print()
        print("FAILED to connect using S3 API. Error details:")
        print(str(exc))
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
