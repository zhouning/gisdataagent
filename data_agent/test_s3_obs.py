import os
import boto3
from dotenv import load_dotenv

# Load the .env file
dotenv_path = r'D:\adk\data_agent\.env'
load_dotenv(dotenv_path)

# Retrieve variables
ak = os.getenv('HUAWEI_OBS_AK')
sk = os.getenv('HUAWEI_OBS_SK')
server = os.getenv('HUAWEI_OBS_SERVER')
bucket = os.getenv('HUAWEI_OBS_BUCKET')

print(f"Endpoint: {server}")
print(f"Bucket: {bucket}")
print(f"AK loaded: {'Yes' if ak and ak != 'your_access_key_here' else 'No'}")
print(f"SK loaded: {'Yes' if sk and sk != 'your_secret_key_here' else 'No'}")

if not ak or ak == 'your_access_key_here':
    print("Please set the actual AK/SK in .env")
    exit(1)

# Initialize boto3 S3 client with Huawei OBS endpoint
try:
    # We use boto3 which is the official AWS SDK for S3
    s3_client = boto3.client(
        's3',
        aws_access_key_id=ak,
        aws_secret_access_key=sk,
        endpoint_url=server,
        region_name='cn-north-4' # Inferring region from endpoint
    )
    
    # Try to access the bucket to verify S3 protocol compatibility
    print("")
    print(f"Attempting to access bucket '{bucket}' using boto3 (native S3 API)...")
    
    # head_bucket checks if bucket exists and we have permission
    s3_client.head_bucket(Bucket=bucket)
    print("Bucket verified successfully!")

    # list_objects_v2 to fetch a few files
    response = s3_client.list_objects_v2(Bucket=bucket, MaxKeys=5)
    
    print("")
    print("SUCCESS! Huawei Cloud OBS is fully compatible with the native S3 API via boto3.")
    if 'Contents' in response:
        print("Found the following objects in the bucket:")
        for obj in response['Contents']:
            print(f" - {obj['Key']} ({obj['Size']} bytes)")
    else:
        print("The bucket is currently empty, but the S3 connection was successful.")
        
except Exception as e:
    print("")
    print("FAILED to connect using S3 API. Error details:")
    print(str(e))
