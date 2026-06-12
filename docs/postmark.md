# Postmark

> Postmark is a reliable transactional email service that helps developers deliver and track application emails. It provides REST APIs, SMTP support, webhooks, and comprehensive email templates to replace traditional SMTP with a scalable, developer-friendly solution.

## Quick Start

To use Postmark for sending emails in your application:

1. Create a Postmark account and verify your sending domain or email address
2. Get your Server API Token from your Postmark server settings
3. Use the REST API or SMTP to send emails
4. Maximum email size is 10 MB (including attachments)
5. Maximum 50 recipients per email (To, CC, BCC combined)

### Authentication

All API requests require authentication using the `X-Postmark-Server-Token` header with your Server API Token:

```
X-Postmark-Server-Token: your-server-token-here
```

For testing without actually sending emails, use `POSTMARK_API_TEST` as your token.

## API Reference

- [Send a single email](https://postmarkapp.com/developer/api/email-api#send-a-single-email): POST to `/email` endpoint
- [Send batch emails](https://postmarkapp.com/developer/api/email-api#send-batch-emails): POST to `/email/batch` endpoint
- [Send with templates](https://postmarkapp.com/developer/api/templates-api#send-email-with-template): POST to `/email/withTemplate` endpoint
- [Send batch with templates](https://postmarkapp.com/developer/api/templates-api#send-batch-with-templates): POST to `/email/batchWithTemplates` endpoint
- [Send bulk emails](https://postmarkapp.com/developer/api/bulk-email): POST to `/email/bulk` endpoint for broadcast streams
- [Template management](https://postmarkapp.com/developer/api/templates-api): Create, edit, list templates via API
- [Bounce API](https://postmarkapp.com/developer/api/bounce-api): Manage bounced emails and reactivate addresses
- [Message tracking](https://postmarkapp.com/developer/api/messages-api): Search and retrieve message details
- [Stats API](https://postmarkapp.com/developer/api/stats-api): Get delivery, open, and click statistics
- [Webhooks](https://postmarkapp.com/developer/webhooks/webhooks-overview): Configure real-time event notifications
- [Server management](https://postmarkapp.com/developer/api/servers-api): Create and configure servers
- [Domain management](https://postmarkapp.com/developer/api/domains-api): Verify domains and configure DKIM/SPF

## Core Concepts

### Message Streams

Postmark separates emails into two types of Message Streams:
- **Transactional**: One-to-one emails triggered by user actions (welcome emails, password resets, order confirmations)
- **Broadcast**: Bulk emails for newsletters, announcements, marketing campaigns

Specify the stream using the `MessageStream` field in your API calls. Most API endpoints default to "outbound" (transactional) stream.

### Key Limitations

- **Email Address**: Must be verified before sending
- **Message Size**: 10 MB total including attachments
- **Recipients**: Maximum 50 total (To, Cc, Bcc combined)
- **Content Size**: TextBody and HtmlBody up to 5 MB each
- **Batch Sending**: 500 messages per call, 50 MB total payload
- **Attachments**: Specific file types allowed (security restriction)
- **Tags**: One tag per message, maximum 1000 characters

### Server Organization

Postmark uses servers to isolate different applications or environments:
- Each server has its own API token
- Separate tracking and statistics per server
- Independent settings for opens/clicks tracking
- Isolated sender signatures and domains

### Message Components

Every email can include:
- **From**: Sender address (must be verified)
- **To/Cc/Bcc**: Recipients (comma-separated for multiple)
- **Subject**: Email subject line
- **TextBody/HtmlBody**: Message content (plain text and/or HTML)
- **MessageStream**: Target stream (transactional or broadcast)
- **Tag**: Category for statistics (optional)
- **Metadata**: Key-value pairs for internal tracking (optional)
- **Headers**: Custom email headers (optional)
- **Attachments**: Files and inline images (optional)
- **TrackOpens/TrackLinks**: Enable tracking (optional)

## Sending Emails

### Single Email API

Send individual transactional emails via HTTP POST to the `/email` endpoint. Full guide: [Send email with API](https://postmarkapp.com/developer/user-guide/send-email-with-api)

**Key Features:**
- Support for HTML, plain text, or multipart messages
- Name formatting: `"John Doe <email@example.com>"`
- Custom headers and metadata support
- Inline image embedding with ContentID
- Maximum 50 recipients total (To, Cc, Bcc combined)
- Tag emails for detailed statistics (one tag per message, max 1000 chars)
- Override sender name while keeping verified email address

**Message Format:**
```json
{
  "From": "sender@example.com",
  "To": "receiver@example.com",
  "Cc": "copied@example.com",
  "Bcc": "blind-copied@example.com",
  "Subject": "Test",
  "Tag": "Invitation",
  "HtmlBody": "<b>Hello</b> <img src=\"cid:image.jpg\"/>",
  "TextBody": "Hello",
  "ReplyTo": "reply@example.com",
  "Metadata": {
    "color": "blue",
    "customer-id": "12345"
  },
  "Headers": [
    {"Name": "CUSTOM-HEADER", "Value": "value"}
  ],
  "TrackOpens": true,
  "TrackLinks": "HtmlOnly",
  "MessageStream": "outbound",
  "Attachments": [
    {
      "Name": "document.pdf",
      "Content": "base64-encoded-content",
      "ContentType": "application/pdf"
    },
    {
      "Name": "image.jpg",
      "ContentID": "cid:image.jpg",
      "Content": "base64-encoded-image",
      "ContentType": "image/jpeg"
    }
  ]
}
```

**Response Format:**
```json
{
  "ErrorCode": 0,
  "Message": "OK",
  "MessageID": "b7bc2f4a-e38e-4336-af7d-e6c392c2f817",
  "SubmittedAt": "2010-11-26T12:01:05.1794748-05:00",
  "To": "receiver@example.com"
}
```

Use the `MessageID` for tracking bounces via webhooks or the bounce API.

### Batch Email API

Send up to 500 emails in a single API call to `/email/batch`. Ideal for high-volume transactional sends with better performance than individual calls.

**Batch Limitations:**
- Maximum 500 messages per API call
- Maximum 50 MB total payload size (including attachments)
- Each message independently validated and sent
- Mixed success/failure responses possible

**Batch Format:**
```json
[
  {
    "From": "sender@example.com",
    "To": "receiver1@example.com",
    "Subject": "Welcome!",
    "TextBody": "Welcome to our service.",
    "HtmlBody": "<html><body><h1>Welcome!</h1></body></html>",
    "MessageStream": "outbound",
    "Tag": "welcome-email"
  },
  {
    "From": "sender@example.com",
    "To": "receiver2@example.com",
    "Subject": "Your order confirmation",
    "TextBody": "Order #12345 confirmed.",
    "HtmlBody": "<html><body>Order confirmed</body></html>",
    "MessageStream": "outbound",
    "Tag": "order-confirmation",
    "Attachments": [
      {
        "Name": "invoice.pdf",
        "Content": "base64-content",
        "ContentType": "application/pdf"
      }
    ]
  }
]
```

**Batch Response:**
Returns an array with individual results for each message:
```json
[
  {
    "ErrorCode": 0,
    "Message": "OK",
    "MessageID": "b7bc2f4a-e38e-4336-af7d-e6c392c2f817",
    "SubmittedAt": "2010-11-26T12:01:05.1794748-05:00",
    "To": "receiver1@example.com"
  },
  {
    "ErrorCode": 406,
    "Message": "Inactive recipient"
  }
]
```

## Code Examples

### Send a Single Email

Basic example with text and HTML:

```bash
curl "https://api.postmarkapp.com/email" \
  -X POST \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "X-Postmark-Server-Token: server-token" \
  -d '{
    "From": "sender@example.com",
    "To": "receiver@example.com",
    "Subject": "Hello from Postmark",
    "TextBody": "Hello dear Postmark user.",
    "HtmlBody": "<html><body><strong>Hello</strong> dear Postmark user.</body></html>",
    "MessageStream": "outbound"
  }'
```

Advanced example with all features:

```bash
curl "https://api.postmarkapp.com/email" \
  -X POST \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "X-Postmark-Server-Token: server-token" \
  -d '{
    "From": "John Sender <sender@example.com>",
    "To": "Jane Receiver <receiver@example.com>",
    "Cc": "manager@example.com",
    "Subject": "Project Update",
    "Tag": "project-updates",
    "HtmlBody": "<h1>Project Status</h1><p>See attached report.</p><img src=\"cid:chart123\">",
    "TextBody": "Project Status\n\nSee attached report.",
    "ReplyTo": "projects@example.com",
    "TrackOpens": true,
    "TrackLinks": "HtmlAndText",
    "MessageStream": "outbound",
    "Metadata": {
      "project_id": "ABC123",
      "client": "Acme Corp"
    },
    "Headers": [
      {"Name": "X-Priority", "Value": "High"}
    ],
    "Attachments": [
      {
        "Name": "report.pdf",
        "Content": "JVBERi0xLjMKJeLjz9M...",
        "ContentType": "application/pdf"
      },
      {
        "Name": "chart.png",
        "ContentID": "cid:chart123",
        "Content": "iVBORw0KGgoAAAANSU...",
        "ContentType": "image/png"
      }
    ]
  }'
```

### Send Batch Emails

Send multiple personalized emails efficiently:

```bash
curl "https://api.postmarkapp.com/email/batch" \
  -X POST \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "X-Postmark-Server-Token: server-token" \
  -d '[
    {
      "From": "sender@example.com",
      "To": "receiver1@example.com",
      "Subject": "Test #1",
      "TextBody": "Hello user 1",
      "MessageStream": "outbound"
    },
    {
      "From": "sender@example.com",
      "To": "receiver2@example.com",
      "Subject": "Test #2",
      "TextBody": "Hello user 2",
      "MessageStream": "outbound"
    }
  ]'
```

### Send with Template

```bash
curl "https://api.postmarkapp.com/email/withTemplate" \
  -X POST \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "X-Postmark-Server-Token: server-token" \
  -d '{
    "From": "sender@example.com",
    "To": "receiver@example.com",
    "TemplateId": 12345,
    "TemplateModel": {
      "name": "John Doe",
      "product_name": "Awesome Product"
    }
  }'
```

### Send Bulk Marketing Email

```bash
curl "https://api.postmarkapp.com/email/bulk" \
  -X POST \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "X-Postmark-Server-Token: server-token" \
  -d '{
    "From": "sender@example.com",
    "Subject": "Newsletter for {{FirstName}}",
    "HtmlBody": "<html><body>Hi, {{FirstName}}</body></html>",
    "TextBody": "Hi, {{FirstName}}",
    "MessageStream": "broadcast",
    "Messages": [
      {
        "To": "user1@example.com",
        "TemplateModel": {"FirstName": "Alice"}
      },
      {
        "To": "user2@example.com",
        "TemplateModel": {"FirstName": "Bob"}
      }
    ]
  }'
```

## Email Features

### Attachments

Include attachments by adding Base64-encoded content. Postmark disallows certain file types to prevent viruses/spyware.

```json
{
  "Attachments": [
    {
      "Name": "document.pdf",
      "Content": "base64-encoded-content-here",
      "ContentType": "application/pdf"
    }
  ]
}
```

**Attachment Limits:**
- Individual TextBody and HtmlBody: 5 MB each
- Total message size with attachments: 10 MB
- Base64 encoding increases size ~33%, but Postmark calculates size after encoding
- Attachments not retrievable via UI, API, or webhooks after sending

### Inline Images

Embed images directly in HTML using Content-ID:

```json
{
  "HtmlBody": "<img src=\"cid:logo123\">",
  "Attachments": [
    {
      "Name": "logo.png",
      "Content": "base64-encoded-image",
      "ContentType": "image/png",
      "ContentID": "cid:logo123"
    }
  ]
}
```

Note: Reference the same image multiple times without duplicating the attachment.

### Tracking

Enable open and click tracking per email or server-wide:

```json
{
  "TrackOpens": true,
  "TrackLinks": "HtmlAndText"
}
```

**TrackLinks Options:**
- `"None"`: No link tracking
- `"HtmlAndText"`: Track links in both HTML and text
- `"HtmlOnly"`: Track links in HTML only
- `"TextOnly"`: Track links in text only

### Custom Headers and Metadata

Add custom headers for email routing and metadata for internal tracking:

```json
{
  "Headers": [
    {"Name": "X-Custom-Header", "Value": "custom-value"},
    {"Name": "Message-ID", "Value": "<unique-id@example.com>"}
  ],
  "Metadata": {
    "customer_id": "12345",
    "order_id": "67890",
    "campaign": "welcome-series"
  }
}
```

Metadata helps track emails internally without affecting delivery.

### Tags

Categorize emails for detailed statistics and reporting (one tag per message):

```json
{
  "Tag": "password-reset"
}
```

Maximum tag length: 1000 characters. Use consistent naming for better analytics.

## Tracking Opens

Open tracking uses an invisible pixel to detect when recipients view your emails. This provides insights into engagement rates, user activity, and email client usage.

**Documentation:**
- [Tracking opens overview](https://postmarkapp.com/developer/user-guide/tracking-opens)
- [Tracking opens per message stream](https://postmarkapp.com/developer/user-guide/tracking-opens/tracking-opens-per-message-stream)
- [Tracking opens per email](https://postmarkapp.com/developer/user-guide/tracking-opens/tracking-opens-per-email)
- [Message opens API](https://postmarkapp.com/developer/user-guide/tracking-opens/message-opens-api)

### How Open Tracking Works

1. **Pixel Insertion**: Invisible 1x1 pixel added to HTML emails
2. **Detection**: Pixel loads when email is viewed
3. **Data Collection**: Client info, location, and timestamp recorded
4. **Analytics**: Data aggregated by tag, message, and account

### Enabling Open Tracking

#### Method 1: Per Message Stream
Configure default tracking for all emails in a stream. Guide: [Tracking opens per message stream](https://postmarkapp.com/developer/user-guide/tracking-opens/tracking-opens-per-message-stream)

```bash
curl "https://api.postmarkapp.com/servers/:serverid" \
  -X PUT \
  -H "Accept: application/json" \
  -H "X-Postmark-Account-Token: account-token" \
  -d '{
    "TrackOpens": true
  }'
```

When enabled at the server level, all HTML emails automatically include tracking.

#### Method 2: Per Email (API)
Enable tracking for individual emails. Guide: [Tracking opens per email](https://postmarkapp.com/developer/user-guide/tracking-opens/tracking-opens-per-email)

```json
{
  "From": "sender@example.com",
  "To": "receiver@example.com",
  "Subject": "Your Order",
  "HtmlBody": "<html>...</html>",
  "TrackOpens": true
}
```

**Note**: Server-level setting overrides per-email settings. You cannot disable tracking per-email if enabled at server level.

#### Method 3: Per Email (SMTP)
Add SMTP header for individual email tracking:

```
X-PM-TrackOpens: true
```

### Open Tracking Data

#### Information Collected
- **Timestamp**: When the email was opened
- **Client**: Email client name and version
- **Platform**: Desktop, WebMail, or Mobile
- **Operating System**: OS name and version
- **Geographic Location**: Country, region, city (when available)
- **IP Address**: Recipient's IP (when available)
- **User Agent**: Browser/client details

#### Sample Open Event Data
```json
{
  "RecordType": "Open",
  "MessageStream": "outbound",
  "FirstOpen": true,
  "MessageID": "883953f4-6105-42a2-a16a-77a8eac79483",
  "Recipient": "john@example.com",
  "ReceivedAt": "2024-11-14T18:24:47Z",
  "Tag": "welcome-email",
  "Client": {
    "Name": "Chrome 119.0",
    "Company": "Google",
    "Family": "Chrome"
  },
  "OS": {
    "Name": "Windows 11",
    "Company": "Microsoft",
    "Family": "Windows"
  },
  "Platform": "Desktop",
  "UserAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)...",
  "Geo": {
    "CountryISOCode": "US",
    "Country": "United States",
    "RegionISOCode": "CA",
    "Region": "California",
    "City": "San Francisco",
    "Zip": "94102",
    "Coords": "37.7749,-122.4194",
    "IP": "192.0.2.1"
  },
  "Metadata": {
    "customer_id": "12345",
    "campaign": "onboarding"
  }
}
```

### Message Opens API

Query and retrieve open tracking data programmatically. Full guide: [Message opens API](https://postmarkapp.com/developer/user-guide/tracking-opens/message-opens-api)

#### Search All Opens
```bash
curl "https://api.postmarkapp.com/messages/outbound/opens?count=25&offset=0" \
  -X GET \
  -H "Accept: application/json" \
  -H "X-Postmark-Server-Token: server-token"
```

#### Filter Opens
```bash
curl "https://api.postmarkapp.com/messages/outbound/opens?\
recipient=john@example.com&\
tag=welcome-email&\
count=25&offset=0" \
  -X GET \
  -H "Accept: application/json" \
  -H "X-Postmark-Server-Token: server-token"
```

#### Opens for Specific Message
```bash
curl "https://api.postmarkapp.com/messages/outbound/opens/{messageid}" \
  -X GET \
  -H "Accept: application/json" \
  -H "X-Postmark-Server-Token: server-token"
```

**Query Parameters:**
- `recipient`: Filter by recipient email
- `tag`: Filter by message tag
- `client_name`: Filter by email client
- `client_company`: Filter by client company
- `client_family`: Filter by client family
- `os_name`: Filter by operating system
- `os_company`: Filter by OS company
- `os_family`: Filter by OS family
- `platform`: Filter by platform (Desktop, WebMail, Mobile)
- `country`: Filter by country
- `region`: Filter by region
- `city`: Filter by city

### Open Tracking Webhook

Receive real-time notifications when emails are opened.

#### Configuration
```bash
curl "https://api.postmarkapp.com/webhooks" \
  -X POST \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "X-Postmark-Server-Token: server-token" \
  -d '{
    "Url": "https://yourapp.com/open-webhook",
    "MessageStream": "outbound",
    "HttpAuth": {
      "Username": "username",
      "Password": "password"
    },
    "Triggers": {
      "Open": {
        "Enabled": true,
        "PostFirstOpenOnly": false
      }
    }
  }'
```

**Options:**
- `PostFirstOpenOnly`: If `true`, only first open is sent. If `false`, every open triggers webhook.

### Limitations and Considerations

#### Technical Limitations
- **HTML Only**: Plain text emails cannot include tracking pixels
- **Image Blocking**: Recipients who block images won't trigger opens
- **Ad Blockers**: May prevent tracking pixel from loading
- **Multiple Opens**: Only first open saved in UI/API unless webhook configured otherwise

#### Privacy Considerations
- **Apple Mail Privacy Protection**: iOS 15+ may pre-fetch images causing false positives
- **Gmail Proxy**: Gmail serves images through proxy, limiting geographic and OS detection
- **Corporate Firewalls**: May block or cache tracking pixels

#### Best Practices
1. **Respect Privacy**: Include unsubscribe options and honor opt-outs
2. **Combine Metrics**: Use opens with clicks for better engagement picture
3. **Test Thoroughly**: Verify tracking works with your email templates
4. **Monitor Trends**: Focus on trends rather than individual opens
5. **Handle False Positives**: Account for privacy protection features

### Open Rate Calculation

```
Open Rate = (Unique Opens / Delivered Emails) × 100
```

**Considerations:**
- Use unique opens (first open only) for accuracy
- Exclude bounced emails from delivered count
- Account for image blocking (typically 20-30% underreporting)
- Compare rates within similar campaign types

### Use Cases

1. **Engagement Analysis**: Identify most engaged subscribers
2. **Re-engagement Campaigns**: Target users who haven't opened recently
3. **A/B Testing**: Compare subject line effectiveness
4. **Send Time Optimization**: Analyze when users open emails
5. **Client Analytics**: Understand email client distribution
6. **Geographic Insights**: Identify regional engagement patterns

## Tracking Links

Link tracking replaces URLs in your emails with tracking URLs that route through Postmark servers, recording click data before redirecting to the original destination. This provides insights into user engagement and content effectiveness.

**Documentation:** [Tracking links](https://postmarkapp.com/developer/user-guide/tracking-links)

### How Link Tracking Works

1. **Link Replacement**: Original URLs replaced with tracking URLs (`click.pstmrk.it`)
2. **Click Detection**: User clicks tracked link
3. **Data Recording**: Browser, location, timestamp captured
4. **Instant Redirect**: User redirected to original URL
5. **Data Storage**: Click information saved for analytics

**Key Features:**
- Works in both HTML and plain text emails
- Links never expire (work indefinitely)
- HTTPS/TLS encryption for all tracked links
- Globally distributed infrastructure for fast redirects
- No dependency on image loading (unlike open tracking)

### Enabling Link Tracking

#### Method 1: Server/Stream Level
Configure default tracking for all emails:

```bash
curl "https://api.postmarkapp.com/servers/:serverid" \
  -X PUT \
  -H "Accept: application/json" \
  -H "X-Postmark-Account-Token: account-token" \
  -d '{
    "TrackLinks": "HtmlAndText"
  }'
```

#### Method 2: Per Email (API)
Enable tracking for individual emails:

```json
{
  "From": "sender@example.com",
  "To": "receiver@example.com",
  "Subject": "Check out our new features",
  "HtmlBody": "<a href=\"https://example.com/features\">View Features</a>",
  "TextBody": "View features at https://example.com/features",
  "TrackLinks": "HtmlAndText"
}
```

#### Method 3: Per Email (SMTP)
Add SMTP header for link tracking:

```
X-PM-TrackLinks: HtmlAndText
```

### Tracking Options

- **`"None"`**: No link tracking (default)
- **`"HtmlAndText"`**: Track links in both HTML and text bodies
- **`"HtmlOnly"`**: Track only HTML links (preserves clean text URLs)
- **`"TextOnly"`**: Track only plain text links

**Important Notes:**
- Identical links in HTML and text count as one unique click
- Each unique link clicked by a recipient triggers a new click event
- Multiple clicks on same link by same recipient = one unique click

### Link Click Data

#### Information Collected
- **Timestamp**: When the link was clicked
- **Original Link**: The destination URL
- **Click Location**: HTML or Text body
- **Platform**: Desktop, WebMail, or Mobile
- **Client Details**: Browser name and version
- **Operating System**: OS information
- **Geographic Data**: Country, region, city (when available)
- **IP Address**: User's IP address
- **Metadata**: Custom metadata from original email

#### Sample Click Event Data
```json
{
  "RecordType": "Click",
  "MessageStream": "outbound",
  "MessageID": "883953f4-6105-42a2-a16a-77a8eac79483",
  "ReceivedAt": "2024-11-14T18:30:45Z",
  "Recipient": "john@example.com",
  "Tag": "product-announcement",
  "OriginalLink": "https://example.com/features",
  "ClickLocation": "HTML",
  "Client": {
    "Name": "Chrome 119.0",
    "Company": "Google",
    "Family": "Chrome"
  },
  "OS": {
    "Name": "Windows 11",
    "Company": "Microsoft",
    "Family": "Windows"
  },
  "Platform": "Desktop",
  "UserAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)...",
  "Geo": {
    "CountryISOCode": "US",
    "Country": "United States",
    "RegionISOCode": "NY",
    "Region": "New York",
    "City": "New York",
    "Zip": "10001",
    "Coords": "40.7128,-74.0060",
    "IP": "192.0.2.1"
  },
  "Metadata": {
    "customer_id": "12345",
    "campaign": "feature-launch"
  }
}
```

### Message Clicks API

Query click data programmatically for analytics and reporting.

#### Search All Clicks
```bash
curl "https://api.postmarkapp.com/messages/outbound/clicks?count=25&offset=0" \
  -X GET \
  -H "Accept: application/json" \
  -H "X-Postmark-Server-Token: server-token"
```

#### Filter Clicks
```bash
curl "https://api.postmarkapp.com/messages/outbound/clicks?\
recipient=john@example.com&\
tag=product-announcement&\
count=25&offset=0" \
  -X GET \
  -H "Accept: application/json" \
  -H "X-Postmark-Server-Token: server-token"
```

#### Clicks for Specific Message
```bash
curl "https://api.postmarkapp.com/messages/outbound/clicks/{messageid}" \
  -X GET \
  -H "Accept: application/json" \
  -H "X-Postmark-Server-Token: server-token"
```

**Query Parameters:**
- `recipient`: Filter by recipient email
- `tag`: Filter by message tag
- `client_name`: Filter by browser/client
- `client_company`: Filter by client company
- `client_family`: Filter by client family
- `os_name`: Filter by operating system
- `os_company`: Filter by OS company
- `os_family`: Filter by OS family
- `platform`: Filter by platform (Desktop, WebMail, Mobile)
- `country`: Filter by country
- `region`: Filter by region
- `city`: Filter by city

### Click Tracking Webhook

Receive real-time notifications when links are clicked.

#### Configuration
```bash
curl "https://api.postmarkapp.com/webhooks" \
  -X POST \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "X-Postmark-Server-Token: server-token" \
  -d '{
    "Url": "https://yourapp.com/click-webhook",
    "MessageStream": "outbound",
    "HttpAuth": {
      "Username": "username",
      "Password": "password"
    },
    "Triggers": {
      "Click": {
        "Enabled": true
      }
    }
  }'
```

#### Webhook Behavior
- One POST per unique click (first click only by default)
- Multiple links = multiple webhook calls
- Clicks older than retention period not tracked
- Data pushed immediately when click occurs

### Custom Link Tracking Domain (Enterprise)

For enterprise customers, Postmark supports custom tracking domains instead of `click.pstmrk.it`:

```
Example: click.yourdomain.com
```

Benefits:
- Brand consistency in URLs
- Improved deliverability
- Greater user trust

### Link Tracking Statistics

#### Click Rate Calculation
```
Click Rate = (Unique Clicks / Delivered Emails) × 100
Click-to-Open Rate = (Unique Clicks / Unique Opens) × 100
```

#### Aggregate Statistics API
```bash
curl "https://api.postmarkapp.com/stats/outbound/clicks?\
tag=welcome-email&\
fromdate=2024-11-01&\
todate=2024-11-30" \
  -X GET \
  -H "Accept: application/json" \
  -H "X-Postmark-Server-Token: server-token"
```

Response includes:
- Total clicks
- Unique clicks
- Click rates by platform
- Browser statistics
- Geographic distribution

### Best Practices

1. **URL Shortening**: Consider original URL length as tracking adds characters
2. **Testing**: Verify tracked links work before sending campaigns
3. **Analytics Tags**: Use consistent tags for better reporting
4. **Privacy Compliance**: Inform users about link tracking in privacy policy
5. **Fallback URLs**: Ensure destination sites handle redirects properly
6. **UTM Parameters**: Combine with tracking for deeper analytics

### Common Use Cases

1. **Call-to-Action Optimization**: Track which CTAs get most clicks
2. **Content Engagement**: Measure interest in different content sections
3. **A/B Testing**: Compare link performance across variations
4. **User Journey Tracking**: Follow user paths through your application
5. **Support Diagnostics**: Verify if users clicked important links
6. **Campaign ROI**: Measure conversion from email to action

### Limitations

- **Link Length**: Tracked URLs are longer than originals
- **Preview Text**: Some clients show tracking URL in previews
- **Security Scanners**: Corporate scanners may trigger false clicks
- **URL Parameters**: Complex parameters preserved but may affect tracking

### Comparison: Open vs Click Tracking

| Feature | Open Tracking | Click Tracking |
|---------|--------------|----------------|
| Method | Invisible pixel | URL replacement |
| Works in | HTML only | HTML and text |
| Requires | Images enabled | User action |
| Reliability | Medium (image blocking) | High (action-based) |
| Data Quality | Subject to false positives | More accurate |

## Managing Your Account

Postmark provides comprehensive account management APIs for configuring servers, domains, and sender authentication. Account-level operations require different authentication than sending emails.

**Documentation:**
- [Managing your account overview](https://postmarkapp.com/developer/user-guide/managing-your-account)
- [Managing sender signatures](https://postmarkapp.com/developer/user-guide/managing-your-account/managing-sender-signatures)
- [Managing servers](https://postmarkapp.com/developer/user-guide/managing-your-account/managing-servers)

### Authentication for Account Management

Account management APIs use different authentication than server operations:

- **Server Operations**: Use `X-Postmark-Server-Token` header with Server API Token
- **Account Operations**: Use `X-Postmark-Account-Token` header with Account API Token

Account API tokens are only accessible by account owners and found in the API Tokens tab.

### Sender Signatures

Sender signatures verify ownership of email addresses used in the From field. Required before sending any emails. Guide: [Managing sender signatures](https://postmarkapp.com/developer/user-guide/managing-your-account/managing-sender-signatures)

#### Create Sender Signature
```bash
curl "https://api.postmarkapp.com/senders" \
  -X POST \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "X-Postmark-Account-Token: account-token" \
  -d '{
    "FromEmail": "notifications@example.com",
    "Name": "Company Notifications",
    "ReplyToEmail": "support@example.com",
    "ConfirmationPersonalNote": "Please confirm this email for our notification system"
  }'
```

**Required Fields:**
- `FromEmail`: Must be a real mailbox on a domain you control
- `Name`: Display name for the sender

**Important Notes:**
- Cannot use public domains (Gmail, Yahoo, etc.)
- Confirmation email sent automatically
- Must have DNS access for DKIM/SPF setup
- Personal note helps recipients understand confirmation context

#### List Sender Signatures
```bash
curl "https://api.postmarkapp.com/senders?count=50&offset=0" \
  -X GET \
  -H "Accept: application/json" \
  -H "X-Postmark-Account-Token: account-token"
```

#### Get Specific Signature
```bash
curl "https://api.postmarkapp.com/senders/{signatureid}" \
  -X GET \
  -H "Accept: application/json" \
  -H "X-Postmark-Account-Token: account-token"
```

#### Resend Confirmation
```bash
curl "https://api.postmarkapp.com/senders/{signatureid}/resend" \
  -X POST \
  -H "Accept: application/json" \
  -H "X-Postmark-Account-Token: account-token"
```

#### Delete Signature
```bash
curl "https://api.postmarkapp.com/senders/{signatureid}" \
  -X DELETE \
  -H "Accept: application/json" \
  -H "X-Postmark-Account-Token: account-token"
```

### Domain Verification

Domain verification allows sending from any address on a verified domain without individual sender signatures. Recommended for organizations sending from multiple addresses.

#### Create Domain
```bash
curl "https://api.postmarkapp.com/domains" \
  -X POST \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "X-Postmark-Account-Token: account-token" \
  -d '{
    "Name": "example.com",
    "ReturnPathDomain": "pm-bounces.example.com"
  }'
```

#### List Domains
```bash
curl "https://api.postmarkapp.com/domains?count=50&offset=0" \
  -X GET \
  -H "Accept: application/json" \
  -H "X-Postmark-Account-Token: account-token"
```

#### Get Domain Details
```bash
curl "https://api.postmarkapp.com/domains/{domainid}" \
  -X GET \
  -H "Accept: application/json" \
  -H "X-Postmark-Account-Token: account-token"
```

Response includes DNS records for configuration:
```json
{
  "Name": "example.com",
  "SPFHost": "example.com",
  "SPFTextValue": "v=spf1 a mx include:spf.mtasv.net ~all",
  "DKIMHost": "20240101._domainkey.example.com",
  "DKIMTextValue": "k=rsa; p=MIGfMA0GCSqG...",
  "DKIMVerified": false,
  "SPFVerified": false,
  "ReturnPathDomain": "pm-bounces.example.com",
  "ReturnPathDomainCNAMEValue": "pm.mtasv.net",
  "ReturnPathDomainVerified": false
}
```

### Email Authentication (DKIM, SPF, Return-Path)

Proper authentication improves deliverability and prevents spoofing.

#### DKIM Setup
1. Add TXT record to DNS:
   - Host: `[selector]._domainkey.yourdomain.com`
   - Value: Provided DKIM key from Postmark

2. Verify DKIM:
```bash
curl "https://api.postmarkapp.com/domains/{domainid}/verifyDkim" \
  -X PUT \
  -H "Accept: application/json" \
  -H "X-Postmark-Account-Token: account-token"
```

#### SPF Setup
1. Add TXT record to DNS:
   - Host: `@` or domain root
   - Value: `v=spf1 a mx include:spf.mtasv.net ~all`

2. Verify SPF:
```bash
curl "https://api.postmarkapp.com/domains/{domainid}/verifyspf" \
  -X POST \
  -H "Accept: application/json" \
  -H "X-Postmark-Account-Token: account-token"
```

#### Return-Path Setup
1. Add CNAME record to DNS:
   - Host: `pm-bounces` (or custom subdomain)
   - Value: `pm.mtasv.net`

2. Verify Return-Path:
```bash
curl "https://api.postmarkapp.com/domains/{domainid}/verifyReturnPath" \
  -X POST \
  -H "Accept: application/json" \
  -H "X-Postmark-Account-Token: account-token"
```

#### Rotate DKIM Keys
For security, rotate DKIM keys periodically:

```bash
curl "https://api.postmarkapp.com/domains/{domainid}/rotatedkim" \
  -X POST \
  -H "Accept: application/json" \
  -H "X-Postmark-Account-Token: account-token"
```

### Server Management

Servers organize emails for different environments, applications, or clients. Each server has unique API tokens, inbound addresses, and statistics. Guide: [Managing servers](https://postmarkapp.com/developer/user-guide/managing-your-account/managing-servers)

#### Create Server
```bash
curl "https://api.postmarkapp.com/servers" \
  -X POST \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "X-Postmark-Account-Token: account-token" \
  -d '{
    "Name": "Production",
    "Color": "blue",
    "SmtpApiActivated": true,
    "RawEmailEnabled": false,
    "DeliveryType": "Live",
    "InboundSpamThreshold": 5,
    "TrackOpens": false,
    "TrackLinks": "None"
  }'
```

**Server Properties:**
- `Name`: Required, identifies the server
- `Color`: Visual identifier in UI
- `SmtpApiActivated`: Enable SMTP sending
- `DeliveryType`: "Live" or "Sandbox"
- `InboundSpamThreshold`: 0-30 in increments of 5
- `TrackOpens`: Default open tracking
- `TrackLinks`: Default link tracking

#### List Servers
```bash
curl "https://api.postmarkapp.com/servers?count=50&offset=0" \
  -X GET \
  -H "Accept: application/json" \
  -H "X-Postmark-Account-Token: account-token"
```

#### Get Server Details
```bash
curl "https://api.postmarkapp.com/servers/{serverid}" \
  -X GET \
  -H "Accept: application/json" \
  -H "X-Postmark-Account-Token: account-token"
```

Response includes:
```json
{
  "ID": 1,
  "Name": "Production",
  "ApiTokens": ["server-api-token"],
  "Color": "blue",
  "SmtpApiActivated": true,
  "DeliveryType": "Live",
  "InboundAddress": "hash@inbound.postmarkapp.com",
  "InboundHash": "hash",
  "InboundHookUrl": "https://yourapp.com/inbound",
  "BounceHookUrl": "https://yourapp.com/bounce",
  "OpenHookUrl": "https://yourapp.com/open",
  "ClickHookUrl": "https://yourapp.com/click",
  "TrackOpens": true,
  "TrackLinks": "HtmlAndText"
}
```

#### Update Server
```bash
curl "https://api.postmarkapp.com/servers/{serverid}" \
  -X PUT \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "X-Postmark-Account-Token: account-token" \
  -d '{
    "Name": "Production v2",
    "TrackOpens": true,
    "TrackLinks": "HtmlAndText",
    "InboundHookUrl": "https://newapp.com/inbound"
  }'
```

#### Delete Server
```bash
curl "https://api.postmarkapp.com/servers/{serverid}" \
  -X DELETE \
  -H "Accept: application/json" \
  -H "X-Postmark-Account-Token: account-token"
```

### Server Organization Strategies

#### By Environment
- Production Server
- Staging Server
- Development Server

Benefits: Separate statistics, easy environment management

#### By Application
- Web App Server
- Mobile App Server
- Admin Dashboard Server

Benefits: Per-application tracking, isolated configurations

#### By Client (Multi-tenant)
- Client A Server
- Client B Server
- Client C Server

Benefits: Complete isolation, per-client billing possible

### Account-Level Settings

#### Default Settings
Configure defaults for new servers:
- Open tracking defaults
- Link tracking defaults
- Inbound spam thresholds
- Webhook configurations

#### API Token Management
- Account tokens: Full account access
- Server tokens: Server-specific operations
- Token rotation for security
- Multiple tokens per server supported

### Best Practices

1. **Authentication Setup**
   - Always configure DKIM and SPF
   - Set up custom Return-Path for DMARC
   - Verify all DNS records before sending

2. **Server Organization**
   - Use descriptive server names
   - Separate production from testing
   - Consider isolation requirements

3. **Security**
   - Rotate API tokens regularly
   - Limit account token access
   - Use HTTPS for all webhooks

4. **Domain Management**
   - Verify entire domains when possible
   - Monitor authentication status
   - Keep DNS records updated

5. **Monitoring**
   - Check sender reputation regularly
   - Monitor authentication failures
   - Track per-server statistics

## SMTP Configuration

Postmark provides SMTP endpoints for easy migration from existing SMTP implementations. This allows you to switch to Postmark without changing your application code - just update your SMTP settings. Full guide: [Send email with SMTP](https://postmarkapp.com/developer/user-guide/send-email-with-smtp)

### SMTP Endpoints

- **Transactional messages**: smtp.postmarkapp.com
- **Broadcast messages**: smtp-broadcasts.postmarkapp.com
- **Ports**: 25, 2525, or 587 (all support TLS)
- **Encryption**: TLS required

### Authentication Methods

Postmark offers two authentication methods for SMTP:

#### Method 1: API Token (Recommended)
Use your Server API Token as both username and password:
- **Username**: Your Server API Token
- **Password**: Your Server API Token
- **Custom Header**: `X-PM-Message-Stream` to specify stream (optional)

```
Username: your-server-api-token
Password: your-server-api-token
```

#### Method 2: SMTP Tokens
For clients that don't support custom headers:
- **Username**: Access Key (from SMTP Token)
- **Password**: Secret Key (from SMTP Token)
- **Note**: SMTP Tokens are unique per message stream

### SMTP Custom Headers

Add Postmark features via SMTP headers:

#### Message Stream Selection
```
X-PM-Message-Stream: outbound
```
If not specified, defaults to the default transactional stream.

#### Tagging
```
X-PM-Tag: welcome-email
```

#### Open Tracking
```
X-PM-Track-Opens: true
```

#### Link Tracking
```
X-PM-Track-Links: HtmlAndText
```
Options: None, HtmlAndText, HtmlOnly, TextOnly

#### Metadata
Add custom metadata with `X-PM-Metadata-` prefix:
```
X-PM-Metadata-customer-id: 12345
X-PM-Metadata-campaign: onboarding
```

#### Preserve Message-ID
Keep your custom Message-ID header:
```
X-PM-KeepID: true
```

### SMTP vs API Comparison

**API Advantages:**
- Immediate error responses with detailed codes
- Batch sending for better performance (up to 500 messages)
- Full access to all Postmark features
- Lower overhead and faster processing
- Retry capabilities with network error handling

**SMTP Advantages:**
- No code changes required for migration
- Works with any SMTP-compatible client
- Familiar protocol for developers

### SMTP Error Handling

SMTP protocol limitations mean errors aren't returned immediately. Instead:
- Errors logged as `SMTPApiError` bounce type
- Monitor bounces via API or webhooks
- Check bounce raw source for detailed error messages
- Set up bounce webhooks for real-time alerts

### Common SMTP Issues and Solutions

#### Authentication Failures
- Verify SMTP is enabled in message stream settings
- Use Server API Token (not Account API Token)
- Check all available ports if one is blocked

#### Recipients Split into Separate Messages
- Some clients (Gmail, Office 365) may not submit all recipients in one transaction
- Use API for guaranteed single message to multiple recipients

#### Character Encoding Issues
- Use Quoted-Printable encoding for best compatibility
- Some combinations of clients and character sets may have issues
- UTF-8 with proper encoding recommended

#### Firewall and Network Issues
- Try all ports (25, 2525, 587) if experiencing connection issues
- Ensure firewall allows outbound SMTP connections
- Some ISPs block port 25

### SMTP Configuration Examples

#### Node.js with Nodemailer
```javascript
const transporter = nodemailer.createTransport({
  host: 'smtp.postmarkapp.com',
  port: 587,
  secure: false,
  auth: {
    user: 'your-server-api-token',
    pass: 'your-server-api-token'
  }
});
```

#### Python with smtplib
```python
import smtplib
server = smtplib.SMTP('smtp.postmarkapp.com', 587)
server.starttls()
server.login('your-server-api-token', 'your-server-api-token')
```

#### PHP with PHPMailer
```php
$mail->isSMTP();
$mail->Host = 'smtp.postmarkapp.com';
$mail->Port = 587;
$mail->SMTPAuth = true;
$mail->Username = 'your-server-api-token';
$mail->Password = 'your-server-api-token';
```

## Inbound Email Processing

Postmark can receive, parse, and deliver inbound emails to your application via webhooks. This enables email-driven features like reply-by-email, email-to-ticket systems, and automated email processing.

**Documentation:**
- [Inbound overview](https://postmarkapp.com/developer/user-guide/inbound)
- [Configure inbound server](https://postmarkapp.com/developer/user-guide/inbound/configure-an-inbound-server)
- [Inbound domain forwarding](https://postmarkapp.com/developer/user-guide/inbound/inbound-domain-forwarding)
- [Parse an email](https://postmarkapp.com/developer/user-guide/inbound/parse-an-email)
- [Configure inbound blocking](https://postmarkapp.com/developer/user-guide/inbound/configure-inbound-blocking)
- [Sample inbound workflow](https://postmarkapp.com/developer/user-guide/inbound/sample-inbound-workflow)

### How It Works

1. **Email Reception**: Send emails to your unique inbound address or custom domain
2. **Parsing**: Postmark parses the email into structured JSON
3. **Webhook Delivery**: JSON payload POSTed to your webhook URL
4. **Processing**: Your application processes the parsed email data

### Setup Steps

#### 1. Configure Inbound Server
Create an Inbound Message Stream and set up your webhook URL. Full guide: [Configure an inbound server](https://postmarkapp.com/developer/user-guide/inbound/configure-an-inbound-server)

- Create an Inbound Message Stream in your Postmark server
- Get your unique inbound email address: `yourhash@inbound.postmarkapp.com`
- Set your webhook URL to receive parsed emails

#### 2. Set Webhook URL
```bash
curl "https://api.postmarkapp.com/servers/:serverid" \
  -X PUT \
  -H "Accept: application/json" \
  -H "X-Postmark-Account-Token: account-token" \
  -d '{
    "InboundHookUrl": "https://yourapp.com/inbound-webhook"
  }'
```

#### 3. Configure Email Forwarding
Two options for receiving emails at your domain:

**Option A: Inbound Domain Forwarding (Recommended)**
Set up MX records to receive emails directly at your domain. Full guide: [Inbound domain forwarding](https://postmarkapp.com/developer/user-guide/inbound/inbound-domain-forwarding)
- Add MX records to your DNS pointing to Postmark
- Emails sent to your domain automatically forwarded to Postmark
- Example: `reply@yourdomain.com` → Postmark → Your webhook

**Option B: Email Forwarding Rules**
- Set up forwarding in your email provider
- Forward emails from `reply@yourdomain.com` to `yourhash@inbound.postmarkapp.com`
- Works without DNS access

### Inbound Webhook Payload

Postmark parses emails into structured JSON. Full details: [Parse an email](https://postmarkapp.com/developer/user-guide/inbound/parse-an-email)

Complete JSON structure sent to your webhook:

```json
{
  "MessageStream": "inbound",
  "From": "sender@example.com",
  "FromName": "John Doe",
  "FromFull": {
    "Email": "sender@example.com",
    "Name": "John Doe",
    "MailboxHash": ""
  },
  "To": "yourhash+customdata@inbound.postmarkapp.com",
  "ToFull": [
    {
      "Email": "yourhash+customdata@inbound.postmarkapp.com",
      "Name": "Your App",
      "MailboxHash": "customdata"
    }
  ],
  "Cc": "cc@example.com",
  "CcFull": [
    {
      "Email": "cc@example.com",
      "Name": "CC User",
      "MailboxHash": ""
    }
  ],
  "Bcc": "bcc@example.com",
  "BccFull": [
    {
      "Email": "bcc@example.com",
      "Name": "BCC User",
      "MailboxHash": ""
    }
  ],
  "ReplyTo": "replyto@example.com",
  "Subject": "Email subject",
  "MessageID": "unique-message-id",
  "Date": "Thu, 14 Nov 2024 15:30:45 +0000",
  "MailboxHash": "customdata",
  "TextBody": "Plain text email content",
  "HtmlBody": "<html><body>HTML email content</body></html>",
  "StrippedTextReply": "Just the reply text without quotes",
  "Tag": "",
  "Headers": [
    {
      "Name": "X-Custom-Header",
      "Value": "custom-value"
    }
  ],
  "Attachments": [
    {
      "Name": "document.pdf",
      "Content": "base64-encoded-content",
      "ContentType": "application/pdf",
      "ContentLength": 12345
    }
  ]
}
```

### Key Payload Fields

- **MailboxHash**: Data after the `+` in email address for threading/identification
- **StrippedTextReply**: Extracted reply text without quoted content
- **FromFull/ToFull/CcFull**: Structured contact information arrays
- **Headers**: All email headers as name/value pairs
- **Attachments**: Base64-encoded file attachments

### Using MailboxHash for Threading

Route replies to the correct thread using the MailboxHash. See real-world example: [Sample inbound workflow](https://postmarkapp.com/developer/user-guide/inbound/sample-inbound-workflow)

```
# Original email sent to:
notifications+order-12345@yourdomain.com

# MailboxHash contains: "order-12345"
```

Best practices:
- Hash sensitive data (SHA1/MD5) before including
- Store hash-to-identifier mappings for lookups
- Avoid including personally identifiable information

### Spam Filtering and Blocking

Configure spam filtering and block unwanted senders. Full guide: [Configure inbound blocking](https://postmarkapp.com/developer/user-guide/inbound/configure-inbound-blocking)

Postmark adds SpamAssassin headers to help identify spam:

```
X-Spam-Status: No
X-Spam-Score: -0.8
X-Spam-Tests: DKIM_SIGNED,DKIM_VALID,RCVD_IN_DNSWL_LOW
X-Spam-Checker-Version: SpamAssassin 3.3.1
```

Use these headers to filter or flag suspicious messages in your application.

### Webhook Security

#### Basic Authentication
Include credentials in webhook URL:
```
https://username:password@yourapp.com/inbound-webhook
```

#### IP Whitelisting
Restrict webhook access to Postmark IP ranges (see support documentation)

#### HTTPS Required
Always use HTTPS for webhook URLs to ensure data encryption

#### Request Validation
- Verify POST method only
- Validate JSON schema matches expected format
- Check for required fields before processing

### Retry Logic

If your webhook doesn't return HTTP 200:
- **Retry Schedule**: 10 retries with exponential backoff (1 minute to 6 hours)
- **403 Response**: Stops retries immediately
- **Failed Messages**: Shown as "Inbound Error" in activity
- **Manual Retry**: Available through Postmark UI

### Testing Inbound Webhooks

#### Using cURL
Test your webhook endpoint with sample data:

```bash
curl https://yourapp.com/inbound-webhook \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "From": "test@example.com",
    "Subject": "Test inbound",
    "TextBody": "Test message body",
    "MessageStream": "inbound"
  }'
```

#### Using RequestBin
1. Create a RequestBin URL at requestbin.com
2. Set as webhook URL in Postmark
3. Send test emails to inspect payload structure

#### Using ngrok for Local Development
```bash
# Expose local port 3000
ngrok http 3000

# Use generated URL as webhook
https://abc123.ngrok.io/inbound-webhook
```

### Inbound Processing Examples

For a complete walkthrough, see: [Sample inbound workflow](https://postmarkapp.com/developer/user-guide/inbound/sample-inbound-workflow)

#### Node.js Express Handler
```javascript
app.post('/inbound-webhook', (req, res) => {
  const { From, Subject, TextBody, Attachments } = req.body;

  // Process email
  console.log(`Email from ${From}: ${Subject}`);

  // Process attachments
  if (Attachments && Attachments.length > 0) {
    Attachments.forEach(attachment => {
      const content = Buffer.from(attachment.Content, 'base64');
      // Save or process attachment
    });
  }

  res.status(200).send('OK');
});
```

#### Python Flask Handler
```python
@app.route('/inbound-webhook', methods=['POST'])
def handle_inbound():
    data = request.get_json()

    # Extract email data
    sender = data.get('From')
    subject = data.get('Subject')
    body = data.get('TextBody')

    # Process reply if present
    if data.get('StrippedTextReply'):
        process_reply(data['StrippedTextReply'])

    return '', 200
```

### Common Use Cases

1. **Reply-by-Email**: Allow users to reply to notifications
2. **Email-to-Ticket**: Convert emails to support tickets
3. **Email Commands**: Process commands sent via email
4. **Document Processing**: Extract and store email attachments
5. **Email Archiving**: Store all inbound communications
6. **Automated Workflows**: Trigger actions based on email content

## Webhook Events

Configure webhooks to receive real-time notifications for:

- **Bounce**: Email bounced
- **Delivery**: Email delivered to recipient server
- **Open**: Email opened (requires tracking enabled)
- **Click**: Link clicked (requires tracking enabled)
- **SpamComplaint**: Marked as spam
- **SubscriptionChange**: Unsubscribe events
- **Inbound**: Incoming email received

Webhook payloads are JSON with event-specific data and Message ID for correlation.

## Error Handling

Common HTTP response codes:

- **200**: Success
- **401**: Unauthorized - check API token
- **422**: Unprocessable Entity - validation error
- **429**: Too Many Requests - rate limited
- **500**: Server Error

Error responses include:
```json
{
  "ErrorCode": 300,
  "Message": "Invalid email address"
}
```

## Libraries and SDKs

- [Official Node.js Library](https://github.com/wildbit/postmark.js): Full-featured library with TypeScript support
- [Official .NET Library](https://github.com/wildbit/postmark-dotnet): NuGet package for C# applications
- [Official Ruby Gem](https://github.com/wildbit/postmark-gem): Ruby implementation
- [Official PHP Library](https://github.com/wildbit/postmark-php): Composer package
- [Official Java Library](https://github.com/wildbit/postmark-java): Maven/Gradle support

## Testing

Use `POSTMARK_API_TEST` as your Server Token to validate API calls without sending emails. For template testing with actual server tokens, send to `test@blackhole.postmarkapp.com`.

## Best Practices

1. Use templates for consistent formatting and easy updates
2. Send attachments from background jobs to avoid blocking requests
3. Implement webhook handlers for bounce and complaint management
4. Use appropriate Message Streams (transactional vs broadcast)
5. Handle errors gracefully with retry logic for temporary failures
6. Tag emails for better tracking and reporting
7. Verify sending domains for better deliverability

## Rate Limits

Postmark handles rate limiting automatically for optimal deliverability. The API will return 429 status codes if you exceed limits. Bulk sends are automatically optimized for delivery speed.

## Support and Resources

- [API Documentation](https://postmarkapp.com/developer/api/overview): Complete API reference
- [User Guides](https://postmarkapp.com/developer/user-guide/overview): Step-by-step tutorials
- [Support Center](https://postmarkapp.com/support): FAQs and troubleshooting
- [Status Page](https://status.postmarkapp.com): Service health monitoring

## Sandbox Mode

Sandbox mode provides a safe testing environment for development, CI/CD integration, and experimentation without sending emails to real recipients. Messages are processed through Postmark's infrastructure but never delivered to actual inboxes.

**Documentation:**
- [Sandbox mode overview](https://postmarkapp.com/developer/user-guide/sandbox-mode)
- [Server sandbox mode](https://postmarkapp.com/developer/user-guide/sandbox-mode/server-sandbox-mode)
- [Generate fake bounces](https://postmarkapp.com/developer/user-guide/sandbox-mode/generate-fake-bounces)

### How Sandbox Mode Works

1. **Full Processing**: Messages go through complete validation and processing
2. **No Delivery**: Emails appear as "Delivered" but never reach recipients
3. **Complete Visibility**: Activity feed, webhooks, and API endpoints work normally
4. **Volume Counting**: Sandbox messages count toward monthly sending limits
5. **Safe Testing**: No risk of accidentally emailing real customers

### Creating a Sandbox Server

#### Via UI
1. Create new server in Postmark account
2. Select "Sandbox" instead of "Live" for Delivery Type
3. Configure as normal server

#### Via API
```bash
curl "https://api.postmarkapp.com/servers" \
  -X POST \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "X-Postmark-Account-Token: account-token" \
  -d '{
    "Name": "Development Testing",
    "Color": "yellow",
    "DeliveryType": "Sandbox"
  }'
```

### Testing Options

#### 1. POSTMARK_API_TEST Token
Use for API validation without creating messages:

```bash
curl "https://api.postmarkapp.com/email" \
  -X POST \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "X-Postmark-Server-Token: POSTMARK_API_TEST" \
  -d '{
    "From": "sender@example.com",
    "To": "test@example.com",
    "Subject": "Test",
    "TextBody": "Testing API"
  }'
```

**Limitations:**
- No activity tracking
- No webhook triggers
- No bounce simulation
- Only validates API structure

#### 2. Black Hole Email Address
Send to `test@blackhole.postmarkapp.com` for testing:

```bash
curl "https://api.postmarkapp.com/email" \
  -X POST \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "X-Postmark-Server-Token: server-token" \
  -d '{
    "From": "sender@example.com",
    "To": "test@blackhole.postmarkapp.com",
    "Subject": "Black hole test",
    "TextBody": "This will be dropped"
  }'
```

**Features:**
- Appears in activity feed
- Counts toward volume
- No actual delivery
- Safe for production servers

### Generating Fake Bounces

Test bounce handling without affecting reputation using the `bounce-testing.postmarkapp.com` domain. Guide: [Generate fake bounces](https://postmarkapp.com/developer/user-guide/sandbox-mode/generate-fake-bounces)

#### Method 1: Dedicated Email Addresses

Send to specific addresses for different bounce types:

| Bounce Type | Email Address |
|-------------|--------------|
| Hard Bounce | `hardbounce@bounce-testing.postmarkapp.com` |
| Soft Bounce | `softbounce@bounce-testing.postmarkapp.com` |
| Transient | `transient@bounce-testing.postmarkapp.com` |
| Unsubscribe | `unsubscribe@bounce-testing.postmarkapp.com` |
| Subscribe | `subscribe@bounce-testing.postmarkapp.com` |
| Auto Responder | `autoresponder@bounce-testing.postmarkapp.com` |
| Address Change | `addresschange@bounce-testing.postmarkapp.com` |
| DNS Error | `dnserror@bounce-testing.postmarkapp.com` |
| Challenge Verification | `challengeverification@bounce-testing.postmarkapp.com` |
| Mailbox Full | `mailboxfull@bounce-testing.postmarkapp.com` |
| Spam Notification | `spamnotification@bounce-testing.postmarkapp.com` |
| Manual Deactivation | `manualdeactivation@bounce-testing.postmarkapp.com` |
| Unconfirmed | `unconfirmed@bounce-testing.postmarkapp.com` |
| Blocked | `blocked@bounce-testing.postmarkapp.com` |
| SMTP API Error | `smtpapierror@bounce-testing.postmarkapp.com` |
| Undeliverable | `undeliverable@bounce-testing.postmarkapp.com` |
| Admin Failure | `adminfailure@bounce-testing.postmarkapp.com` |
| Template Render | `templaterender@bounce-testing.postmarkapp.com` |
| Connection Timeout | `connectiontimeout@bounce-testing.postmarkapp.com` |
| SPF Validation | `spfvalidation@bounce-testing.postmarkapp.com` |
| Spam Complaint | Not supported (defaults to Hard Bounce) |

**Format Variations:**
- Case insensitive: `HardBounce@bounce-testing.postmarkapp.com`
- Underscores allowed: `hard_bounce@bounce-testing.postmarkapp.com`
- Camel case supported: `Hard_Bounce@bounce-testing.postmarkapp.com`

#### Method 2: Custom Header

Use `X-PM-Bounce-Type` header with any recipient at bounce-testing domain:

```bash
curl "https://api.postmarkapp.com/email" \
  -X POST \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "X-Postmark-Server-Token: server-token" \
  -d '{
    "From": "sender@example.com",
    "To": "anything@bounce-testing.postmarkapp.com",
    "Subject": "Bounce test",
    "TextBody": "Testing bounce handling",
    "Headers": [{
      "Name": "X-PM-Bounce-Type",
      "Value": "SoftBounce"
    }]
  }'
```

**Header Values:**
- `HardBounce`
- `SoftBounce`
- `Transient`
- `Unsubscribe`
- `Subscribe`
- `AutoResponder`
- `AddressChange`
- `DnsError`
- `ChallengeVerification`
- `MailboxFull`
- `SpamNotification`
- `ManualDeactivation`
- `Unconfirmed`
- `Blocked`
- `SMTPApiError`
- `Undeliverable`
- `AdminFailure`
- `TemplateRender`
- `ConnectionTimeout`
- `SpfValidation`

### Fake Bounce Behavior

**Important Notes:**
- Bounces appear in activity and statistics
- Webhook notifications triggered
- Hard bounces added to suppression list
- Must reactivate addresses for retesting hard bounces
- Counts toward monthly volume
- Spam complaints not supported (default to hard bounce)

### Testing Webhooks with Sandbox

Sandbox servers trigger all webhooks normally:

```bash
# Configure webhook for sandbox server
curl "https://api.postmarkapp.com/webhooks" \
  -X POST \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "X-Postmark-Server-Token: sandbox-server-token" \
  -d '{
    "Url": "https://yourapp.com/test-webhook",
    "MessageStream": "outbound",
    "Triggers": {
      "Bounce": {
        "Enabled": true
      },
      "Open": {
        "Enabled": true
      },
      "Click": {
        "Enabled": true
      }
    }
  }'
```

### CI/CD Integration

#### GitHub Actions Example
```yaml
name: Email Tests
on: [push]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Run Email Tests
        env:
          POSTMARK_SERVER_TOKEN: ${{ secrets.POSTMARK_SANDBOX_TOKEN }}
        run: |
          npm test
```

#### Environment Configuration
```javascript
// config.js
const config = {
  postmark: {
    serverToken: process.env.NODE_ENV === 'production'
      ? process.env.POSTMARK_LIVE_TOKEN
      : process.env.POSTMARK_SANDBOX_TOKEN,
    deliveryType: process.env.NODE_ENV === 'production'
      ? 'Live'
      : 'Sandbox'
  }
};
```

### Testing Strategies

#### 1. Development Environment
- Use sandbox server for all development
- Test webhooks with local ngrok tunnel
- Generate various bounce types for error handling

#### 2. Staging Environment
- Mirror production configuration
- Use sandbox mode with real addresses
- Test full email workflows safely

#### 3. Production Testing
- Use black hole address for smoke tests
- Monitor with separate test tags
- Validate critical paths without customer impact

#### 4. Email Aliases for Testing
Gmail and other providers support aliases:
- `user+test1@gmail.com`
- `user+test2@gmail.com`
- All deliver to `user@gmail.com`

### Best Practices

1. **Separate Servers**
   - Development: Sandbox server
   - Staging: Sandbox server
   - Production: Live server with test addresses

2. **Webhook Testing**
   - Use RequestBin for initial development
   - Test all webhook types with fake bounces
   - Validate webhook signatures in sandbox

3. **Volume Management**
   - Remember sandbox counts toward limits
   - Clean up test data regularly
   - Monitor sandbox usage separately

4. **Safe Testing**
   - Never use real customer emails in tests
   - Maintain test email lists separately
   - Use descriptive tags for test messages

5. **Bounce Testing**
   - Test all bounce types your app handles
   - Verify suppression list management
   - Test reactivation workflows

### Transitioning from Sandbox to Live

1. **Verify Configuration**
   - Confirm all sender signatures/domains
   - Check authentication (DKIM, SPF, Return-Path)
   - Review webhook URLs

2. **Update Server Settings**
   ```bash
   curl "https://api.postmarkapp.com/servers/{serverid}" \
     -X PUT \
     -H "Accept: application/json" \
     -H "Content-Type: application/json" \
     -H "X-Postmark-Account-Token: account-token" \
     -d '{
       "DeliveryType": "Live"
     }'
   ```

3. **Test with Small Batch**
   - Send to internal team first
   - Monitor delivery and engagement
   - Check for unexpected bounces

4. **Monitor Closely**
   - Watch bounce rates
   - Check spam complaints
   - Review delivery statistics

### Limitations

- **Sandbox Mode:**
  - Cannot test actual inbox delivery
  - No real bounce reasons from ISPs
  - Opens/clicks cannot be simulated

- **POSTMARK_API_TEST Token:**
  - No activity visibility
  - No webhook triggers
  - Cannot test templates

- **Fake Bounces:**
  - Spam complaints not supported
  - Some bounce types may not match real ISP responses
  - Hard bounces require reactivation for retesting

## Optional

- [SMTP Configuration Guide](https://postmarkapp.com/developer/user-guide/send-email-with-smtp): Detailed SMTP setup instructions
- [Inbound Email Processing](https://postmarkapp.com/developer/user-guide/process-email): Parse incoming emails
- [Sandbox Mode](https://postmarkapp.com/developer/user-guide/sandbox-mode): Test without sending real emails
- [Managing Sender Signatures](https://postmarkapp.com/developer/user-guide/managing-sender-signatures): Domain and email verification
- [Postmark MCP Server](https://github.com/ActiveCampaign/postmark-mcp): Official Postmark MCP server
