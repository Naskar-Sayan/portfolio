#!/usr/bin/env python3
"""Optional WhatsApp Cloud API sender for data/alerts.json.
Credentials are supplied by environment variables; none are stored in Git."""
import argparse, json, os, sys
import requests

def main():
    p=argparse.ArgumentParser(); p.add_argument('--input',default='data/alerts.json'); a=p.parse_args()
    try:
        with open(a.input,encoding='utf-8') as f: digest=json.load(f)
    except (FileNotFoundError,json.JSONDecodeError,OSError):
        print('No alert digest; skipping.'); return 0
    if digest.get('baseline'):
        print('Initial baseline; skipping first notification.'); return 0
    token=os.getenv('WHATSAPP_ACCESS_TOKEN'); phone_id=os.getenv('WHATSAPP_PHONE_NUMBER_ID'); recipient=os.getenv('WHATSAPP_RECIPIENT'); version=os.getenv('WHATSAPP_API_VERSION','v23.0')
    if not all((token,phone_id,recipient)):
        print('WhatsApp credentials not configured; skipping send.'); return 0
    s=digest.get('summary',{}); body='🇮🇳 Government Jobs Alert\n\nNew: %s\nUpdated: %s\nClosing within 3 days: %s\n\n%s' % (s.get('new_jobs',0),s.get('updated_jobs',0),s.get('deadline_alerts',0),digest.get('notification_text','No new actionable alerts.'))
    url='https://graph.facebook.com/%s/%s/messages' % (version,phone_id)
    payload={'messaging_product':'whatsapp','to':recipient,'type':'text','text':{'preview_url':True,'body':body[:4096]}}
    r=requests.post(url,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},json=payload,timeout=20)
    if not r.ok:
        print('WhatsApp API error %s: %s' % (r.status_code,r.text[:1000]),file=sys.stderr); return 1
    print('WhatsApp alert sent.'); return 0
if __name__=='__main__': raise SystemExit(main())
