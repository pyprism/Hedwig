import time

import boto3
import json
import email
from email import policy

SQS_QUEUE_URL = ""
S3_BUCKET = ''
AWS_ACCESS_KEY_ID = ''
AWS_SECRET_ACCESS_KEY = ''
AWS_DEFAULT_REGION = 'us-east-1'

sqs = boto3.client('sqs', region_name=AWS_DEFAULT_REGION,
                       aws_access_key_id=AWS_ACCESS_KEY_ID,
                       aws_secret_access_key=AWS_SECRET_ACCESS_KEY)
s3 = boto3.client('s3', region_name=AWS_DEFAULT_REGION,
                      aws_access_key_id=AWS_ACCESS_KEY_ID,
                      aws_secret_access_key=AWS_SECRET_ACCESS_KEY
                      )

def process_email_from_s3(s3_bucket, s3_key):
    print(f"Fetching: s3://{s3_bucket}/{s3_key}")
    obj = s3.get_object(Bucket=s3_bucket, Key=s3_key)
    raw_email = obj["Body"].read()
    msg = email.message_from_bytes(raw_email, policy=policy.default)
    print("raw body", msg)
    subject = msg["subject"]
    sender = msg["from"]
    to = msg["to"]
    body = msg.get_body(preferencelist=('plain', 'html')).get_content()
    print("====== Email Received ======")
    print("From:", sender)
    print("To:", to)
    print("Subject:", subject)
    print("Body:\n", body[:500])
    print("============================")

def delete_email_from_s3(bucket, key):
    try:
        s3.delete_object(Bucket=bucket, Key=key)
        print(f"Deleted: s3://{bucket}/{key}")
    except Exception as e:
        print(f"Failed to delete {key}: {e}")

def delete_message_from_sqs(receipt_handle):
    try:
        sqs.delete_message(
            QueueUrl=SQS_QUEUE_URL,
            ReceiptHandle=receipt_handle
        )
        print("Message deleted from SQS")
    except Exception as e:
        print("Failed to delete message from SQS:", e)

def poll():
    print("Starting to poll SQS for messages...")
    response = sqs.receive_message(
            QueueUrl=SQS_QUEUE_URL,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=20
        )
    print("Received response:", response)
    messages = response.get("Messages", [])
    print("Number of messages received:", len(messages))
    for message in messages:
        print("Processing message:", message["MessageId"])
        try:
            body = json.loads(message["Body"])
            print("Message body:", body)
            for record in body.get("Records", []):
                print("record:", record)
                s3_key = record["s3"]["object"]["key"]
                print("Processing S3 key:", s3_key)
                process_email_from_s3(S3_BUCKET, s3_key)
                print("Processed message:", message["MessageId"])
                delete_email_from_s3(S3_BUCKET, s3_key)
        except Exception as e:
            print("Error:", e)

        # delete message after processing
        delete_message_from_sqs(message["ReceiptHandle"])


        # Short sleep before next poll
        #time.sleep(2)


if __name__ == "__main__":
    poll()
