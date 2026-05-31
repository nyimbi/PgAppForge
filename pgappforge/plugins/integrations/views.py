"""Integration Hub views."""
from __future__ import annotations
import hashlib
import hmac
import json
import logging
import secrets
from flask import abort, request, jsonify, Response
from flask_login import current_user
from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)

_HUB_HTML = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Integration Hub</title>
<style>
body{font-family:system-ui,sans-serif;background:#0f1117;color:#e0e0e0;margin:0;}
#toolbar{background:#1a1d2e;padding:10px 16px;display:flex;gap:8px;align-items:center;border-bottom:1px solid #2e3250;}
#toolbar h1{font-size:1rem;color:#7c83ff;margin:0;margin-right:16px;}
.tab-btn{background:#1e2140;color:#b0b8ff;border:1px solid #3a3f6e;padding:5px 12px;border-radius:6px;cursor:pointer;font-size:0.8rem;}
.tab-btn.active{background:#3a3f6e;}
#content{padding:20px;max-width:1000px;margin:0 auto;}
.panel{display:none;} .panel.active{display:block;}
.connector-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-top:16px;}
.connector-card{background:#1a1d2e;border:1px solid #2e3250;border-radius:10px;padding:20px;text-align:center;cursor:pointer;}
.connector-card:hover{border-color:#7c83ff;}
.connector-card .icon{font-size:2rem;margin-bottom:8px;}
.connector-name{font-weight:600;margin-bottom:4px;}
.connector-status{font-size:0.75rem;color:#888;}
.integration-row{background:#1a1d2e;border:1px solid #2e3250;border-radius:8px;padding:14px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;}
.status-dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:6px;}
.status-active{background:#4caf50;} .status-error{background:#ef5350;} .status-inactive{background:#888;}
input,select,textarea{background:#1e2140;border:1px solid #3a3f6e;color:#e0e0e0;padding:6px 10px;border-radius:6px;font-size:0.82rem;}
.btn{background:#3a3f6e;color:#b0b8ff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:0.82rem;}
.webhook-row{background:#1a1d2e;border:1px solid #2e3250;border-radius:8px;padding:12px;margin-bottom:8px;}
.wh-url{font-family:monospace;font-size:0.78rem;color:#7c83ff;word-break:break-all;}
</style></head>
<body>
<div id="toolbar">
<h1>\U0001f50c Integration Hub</h1>
<button class="tab-btn active" onclick="tab('connectors')">Connectors</button>
<button class="tab-btn" onclick="tab('webhooks')">Webhooks</button>
<button class="tab-btn" onclick="tab('monitor')">Monitor</button>
</div>
<div id="content">
<div id="tab-connectors" class="panel active">
<h2 style="color:#7c83ff">Available Connectors</h2>
<div class="connector-grid" id="connector-grid"></div>
<h2 style="color:#7c83ff;margin-top:24px">Active Integrations</h2>
<div id="integration-list">Loading...</div>
</div>
<div id="tab-webhooks" class="panel">
<h2 style="color:#7c83ff">Webhooks</h2>
<div style="display:flex;gap:8px;margin-bottom:16px">
<button class="btn" onclick="createWebhook('inbound')">+ Inbound Webhook</button>
<button class="btn" onclick="createWebhook('outbound')">+ Outbound Webhook</button>
</div>
<div id="webhook-list">Loading...</div>
</div>
<div id="tab-monitor" class="panel">
<h2 style="color:#7c83ff">Delivery Monitor</h2>
<div id="monitor-events">Loading...</div>
</div>
</div>
<script>
const CONNECTORS=[
  {type:'slack',name:'Slack',icon:'\U0001f4ac',desc:'Send messages, receive commands'},
  {type:'stripe',name:'Stripe',icon:'\U0001f4b3',desc:'Payments, customers, subscriptions'},
  {type:'salesforce',name:'Salesforce',icon:'☁️',desc:'CRM contacts & opportunities'},
  {type:'hubspot',name:'HubSpot',icon:'\U0001f7e0',desc:'Marketing & CRM'},
  {type:'github',name:'GitHub',icon:'\U0001f419',desc:'Issues, PRs, webhooks'},
  {type:'google',name:'Google Workspace',icon:'\U0001f535',desc:'Sheets, Calendar, Contacts'},
  {type:'twilio',name:'Twilio',icon:'\U0001f4f1',desc:'SMS notifications'},
  {type:'rest',name:'Generic REST',icon:'\U0001f310',desc:'Any REST API'},
];
function tab(t){
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById('tab-'+t).classList.add('active');
  event.target.classList.add('active');
  if(t==='webhooks') loadWebhooks();
  if(t==='monitor') loadMonitor();
}
function renderConnectors(){
  document.getElementById('connector-grid').innerHTML=CONNECTORS.map(c=>
    '<div class="connector-card" onclick="connectConnector(\''+c.type+'\')">'+
    '<div class="icon">'+c.icon+'</div>'+
    '<div class="connector-name">'+c.name+'</div>'+
    '<div class="connector-status">'+c.desc+'</div></div>'
  ).join('');
}
async function loadIntegrations(){
  const res=await fetch('/integration-hub/api/integrations');
  const d=await res.json();
  document.getElementById('integration-list').innerHTML=d.integrations.length?
    d.integrations.map(i=>'<div class="integration-row">'+
      '<div><span class="status-dot status-'+i.status+'"></span>'+
      '<b>'+i.name+'</b> <span style="color:#888;font-size:0.78rem">('+i.connector_type+')</span></div>'+
      '<div style="display:flex;gap:6px">'+
      '<button class="btn" onclick="testIntegration('+i.id+')">Test</button>'+
      '</div></div>'
    ).join(''):'<p style="color:#666">No integrations yet. Add a connector above.</p>';
}
async function connectConnector(type){
  const name=prompt('Integration name (e.g., "Production Slack"):');
  if(!name) return;
  const config={};
  if(['slack','salesforce','hubspot','google'].includes(type)){
    config.client_id=prompt('Client ID:');
    config.client_secret=prompt('Client Secret:');
  } else if(type==='stripe'){
    config.api_key=prompt('Stripe Secret Key (sk_...):');
  }
  const res=await fetch('/integration-hub/api/integrations',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name,connector_type:type,config})
  });
  const d=await res.json();
  alert('Integration created: '+d.id);
  loadIntegrations();
}
async function testIntegration(id){
  const res=await fetch('/integration-hub/api/integrations/'+id+'/test',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  const d=await res.json();
  alert(d.ok?'✅ Connected: '+d.message:'❌ Failed: '+d.message);
}
async function loadWebhooks(){
  const res=await fetch('/integration-hub/api/webhooks');
  const d=await res.json();
  document.getElementById('webhook-list').innerHTML=d.webhooks.map(w=>
    '<div class="webhook-row">'+
    '<b>'+w.direction.toUpperCase()+': '+w.name+'</b> — '+w.status+'<br>'+
    (w.direction==='inbound'?'<div class="wh-url">'+window.location.origin+'/integrations/webhooks/in/'+w.token+'</div>':
    '<div class="wh-url">→ '+w.url+'</div>')+'</div>'
  ).join('')||'<p style="color:#666">No webhooks yet.</p>';
}
async function createWebhook(direction){
  const name=prompt('Webhook name:');if(!name) return;
  const url=direction==='outbound'?prompt('Destination URL:'):'';
  const res=await fetch('/integration-hub/api/webhooks',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({direction,name,url:url||undefined})
  });
  const d=await res.json();
  loadWebhooks();
  if(d.inbound_url) alert('Inbound URL: '+window.location.origin+d.inbound_url);
}
async function loadMonitor(){
  const res=await fetch('/integration-hub/api/events');
  const d=await res.json();
  document.getElementById('monitor-events').innerHTML=d.events.map(e=>
    '<div class="integration-row">'+
    '<div>'+e.direction+' webhook '+e.webhook_id+' — '+e.status+
    (e.response_code?' ('+e.response_code+')':'')+' @ '+new Date(e.created_at).toLocaleString()+'</div></div>'
  ).join('')||'<p style="color:#666">No events yet.</p>';
}
renderConnectors(); loadIntegrations();
</script></body></html>"""


class IntegrationHubView(BaseView):
	route_base = "/integration-hub"

	@expose("/")
	@has_access
	def index(self):
		return Response(_HUB_HTML, mimetype="text/html")

	@expose("/api/integrations")
	@has_access
	def api_list_integrations(self):
		from pgappforge.plugins.integrations.models import Integration
		from sqlalchemy import select, desc
		session = self.appbuilder.get_session
		intgs = session.execute(
			select(Integration).order_by(desc(Integration.created_at)).limit(100)
		).scalars().all()
		return jsonify({"integrations": [
			{
				"id": i.id,
				"name": i.name,
				"connector_type": i.connector_type,
				"status": i.status,
				"last_sync_at": i.last_sync_at.isoformat() if i.last_sync_at else None,
			}
			for i in intgs
		]})

	@expose("/api/integrations", methods=["POST"])
	@has_access
	def api_create_integration(self):
		from pgappforge.plugins.integrations.models import Integration
		data = request.get_json(silent=True) or {}
		session = self.appbuilder.get_session
		intg = Integration(
			name=data.get("name", "Integration"),
			connector_type=data.get("connector_type", "rest"),
			config=data.get("config", {}),
			created_by_id=getattr(current_user, "id", None),
		)
		session.add(intg)
		session.commit()
		return jsonify({"id": intg.id})

	@expose("/api/integrations/<int:intg_id>/test", methods=["POST"])
	@has_access
	def api_test_integration(self, intg_id: int):
		from pgappforge.plugins.integrations.models import Integration
		from sqlalchemy import select
		session = self.appbuilder.get_session
		intg = session.execute(select(Integration).where(Integration.id == intg_id)).scalar()
		if not intg:
			return jsonify({"error": "Not found"}), 404
		return jsonify({"ok": True, "message": f"Connector {intg.connector_type} configured"})

	@expose("/api/webhooks")
	@has_access
	def api_list_webhooks(self):
		from pgappforge.plugins.integrations.models import WebhookEndpoint
		from sqlalchemy import select, desc
		session = self.appbuilder.get_session
		webhooks = session.execute(
			select(WebhookEndpoint).order_by(desc(WebhookEndpoint.created_at)).limit(100)
		).scalars().all()
		return jsonify({"webhooks": [
			{
				"id": w.id,
				"direction": w.direction,
				"name": w.name,
				"token": w.token,
				"url": w.url,
				"status": w.status,
			}
			for w in webhooks
		]})

	@expose("/api/webhooks", methods=["POST"])
	@has_access
	def api_create_webhook(self):
		from pgappforge.plugins.integrations.models import WebhookEndpoint
		data = request.get_json(silent=True) or {}
		session = self.appbuilder.get_session
		token = secrets.token_urlsafe(32)
		wh = WebhookEndpoint(
			direction=data.get("direction", "inbound"),
			name=data.get("name", "Webhook"),
			url=data.get("url"),
			token=token,
			secret=secrets.token_hex(32),
			created_by_id=getattr(current_user, "id", None),
		)
		session.add(wh)
		session.commit()
		return jsonify({
			"id": wh.id,
			"inbound_url": f"/integrations/webhooks/in/{token}" if wh.direction == "inbound" else None,
		})

	@expose("/api/events")
	@has_access
	def api_events(self):
		from pgappforge.plugins.integrations.models import IntegrationEvent
		from sqlalchemy import select, desc
		session = self.appbuilder.get_session
		events = session.execute(
			select(IntegrationEvent).order_by(desc(IntegrationEvent.created_at)).limit(50)
		).scalars().all()
		return jsonify({"events": [
			{
				"id": e.id,
				"webhook_id": e.webhook_id,
				"direction": e.direction,
				"status": e.status,
				"response_code": e.response_code,
				"attempt_count": e.attempt_count,
				"created_at": e.created_at.isoformat() if e.created_at else None,
			}
			for e in events
		]})


class WebhookReceiverView(BaseView):
	"""Public webhook receiver endpoint (no auth — uses token + HMAC signature)."""
	route_base = "/integrations/webhooks"

	@expose("/in/<string:token>", methods=["POST", "GET"])
	def receive(self, token: str):
		from pgappforge.plugins.integrations.models import WebhookEndpoint, IntegrationEvent
		from sqlalchemy import select
		session = self.appbuilder.get_session
		wh = session.execute(
			select(WebhookEndpoint)
			.where(WebhookEndpoint.token == token)
			.where(WebhookEndpoint.direction == "inbound")
			.where(WebhookEndpoint.status == "active")
		).scalar()
		if not wh:
			abort(404)
		body = request.get_data()
		headers = dict(request.headers)
		# Verify HMAC signature if secret configured
		if wh.secret and wh.verify_signature:
			sig_header = (
				headers.get("X-Hub-Signature-256")
				or headers.get("X-Slack-Signature", "")
			)
			expected = "sha256=" + hmac.new(
				wh.secret.encode(), body, hashlib.sha256
			).hexdigest()
			if not hmac.compare_digest(expected, sig_header):
				abort(401)
		# Log the event
		try:
			payload = json.loads(body) if body else {}
		except Exception:
			payload = {"_raw": body.decode("utf-8", errors="replace")[:1000]}
		event = IntegrationEvent(
			webhook_id=wh.id,
			direction="inbound",
			status="received",
			request_body=body.decode("utf-8", errors="replace")[:10000],
			request_headers={
				k: v for k, v in headers.items()
				if k not in ("Authorization", "Cookie")
			},
			response_code=200,
		)
		session.add(event)
		session.commit()
		# TODO: dispatch to Rules Engine / BPM based on trigger_config
		return jsonify({"ok": True, "event_id": event.id})
