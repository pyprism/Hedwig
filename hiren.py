import boto3
from botocore.exceptions import ClientError

def send_email():
    ses = boto3.client(
        'ses',
        region_name='us-east-1',
        aws_access_key_id='',
        aws_secret_access_key=''
    )

    try:
        response = ses.send_email(
            Source='',
            Destination={
                'ToAddresses': ['']
            },
            Message={
                'Subject': {'Data': 'Test Email from SES'},
                'Body': {
                    'Text': {'Data': 'Hello, this is a test email sent using Amazon SES and boto3.'}
                }
            }
        )
        print("Email sent! Message ID:", response['MessageId'])

    except ClientError as e:
        print("Error:", e.response['Error']['Message'])

if __name__ == "__main__":
    send_email()

