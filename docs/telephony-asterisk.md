# Telephony setup: Asterisk (SIP) with a Bangladeshi IPTSP trunk

This sets up phase 1 of the telephony plan (`docs/roadmap.md`, section 2): click-to-call from the Agent
Studio, and call logs in Frappe CRM.

## 1. Trunks and routing (on the PBX)

- **Bangladesh:** a SIP trunk from a BTRC-licensed IPTSP, with your 09-series number as caller ID.
- **International:** an international SIP carrier, or Twilio Elastic SIP.

The app sends the number as E.164 digits without the plus (for example `8801711123456`). It reaches the
dial-plan context you set in Sales Agent Settings (`from-internal` by default). Route on the prefix:

```
[from-internal]
exten => _880X.,1,Set(CALLERID(num)=${RECKON_CALLER_ID})
 same => n,Dial(PJSIP/0${EXTEN:3}@iptsp-trunk,60)
 same => n,Hangup()
exten => _X.,1,Dial(PJSIP/+${EXTEN}@international-trunk,60)
 same => n,Hangup()
```

Adjust the dial string to the format your IPTSP expects: `0` plus the national number, or `880…`.

## 2. ARI user (for click-to-call)

`/etc/asterisk/ari.conf`:

```
[general]
enabled = yes
[reckon]
type = user
password = <a long random password>
```

Serve ARI over **HTTPS only**, with `http.conf` `tlsenable=yes`. In Sales Agent Settings → Phone system, set:
- Calls go through: **Asterisk (SIP)**;
- ARI URL: `https://pbx.example.com:8089`;
- ARI user and password;
- context and caller ID.

Each salesperson's extension goes in **CRM Telephony Agent → SIP extension**. On click-to-call, their phone
or softphone rings first; when they answer, the lead is dialled.

## 3. Call events (call logs in the CRM)

Send each call's result to

```
POST https://<your site>/api/method/reckon_sales_agent.api_telephony.call_event
Header: X-Reckon-Signature: sha256=<HMAC-SHA256 of the raw body with the "Call events secret">
Body (JSON): {"company": "<Company>", "call_id": "${UNIQUEID}", "dialstatus": "ANSWER", "direction": "outbound",
              "src": "201", "dst": "8801711123456", "billsec": 42, "extension": "201",
              "recording_url": "https://…", "reference": "${RECKON_REFERENCE}"}
```

A hangup handler can call a small script. For example, `/usr/local/bin/reckon-call-event`:

```python
#!/usr/bin/env python3
import hashlib, hmac, json, sys, urllib.request
secret, url, company = "<call events secret>", "https://<site>/api/method/reckon_sales_agent.api_telephony.call_event", "<Company>"
call_id, status, direction, src, dst, billsec, ext, ref = sys.argv[1:9]
body = json.dumps({"company": company, "call_id": call_id, "dialstatus": status, "direction": direction,
                   "src": src, "dst": dst, "billsec": billsec, "extension": ext, "reference": ref}).encode()
sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
req = urllib.request.Request(url, body, {"Content-Type": "application/json", "X-Reckon-Signature": "sha256=" + sig})
urllib.request.urlopen(req, timeout=10)
```

The app writes Frappe CRM's own **CRM Call Log**, linked to the lead. An inbound call (direction `inbound`,
status `RINGING` or `NOANSWER`) notifies the lead's owner. Click-to-call calls carry `RECKON_REFERENCE`, so the
log links to the right lead even before the number is matched.

## Compliance reminders

- Use a licensed IPTSP only; never route Bangladeshi calls over an unlicensed ("grey") route.
- Announce recording if you record, and keep recordings under your retention policy.
- Call only between 09:00 and 20:00 Bangladesh time. The suppression list blocks calls to anyone who opted out.
