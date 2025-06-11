import time

import boto3
import json
import email
from email import policy

SQS_QUEUE_URL = ""
S3_BUCKET = ''
AWS_ACCESS_KEY_ID = ''
AWS_SECRET_ACCESS_KEY = ''
AWS_DEFAULT_REGION = ''

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

    subject = msg["subject"]
    sender = msg["from"]
    to = msg["to"]
    body = msg.get_body(preferencelist=('plain', 'html')).get_content()
    print("$$$$$$$$\n")
    print("====== Email Received ======")
    print("From:", sender)
    print("To:", to)
    print("Subject:", subject)
    print("Body:\n", body[:500])
    print("============================")

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
        except Exception as e:
            print("Error:", e)

        # delete message after processing
        # sqs.delete_message(
        #         QueueUrl=SQS_QUEUE_URL,
        #         ReceiptHandle=message["ReceiptHandle"]
        # )

        # Short sleep before next poll
        #time.sleep(2)


if __name__ == "__main__":
    poll()
