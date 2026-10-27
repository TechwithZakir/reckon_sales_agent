// Reckon website chat: a chat button for a Company's own website.
// <script src="https://<site>/assets/reckon_sales_agent/js/reckon_webchat.js" data-site="https://<site>" data-key="<key>" defer></script>
// Visitors write; the Company's AI drafts an answer that a person approves, and the answer appears here.
// Runs in a Shadow DOM so the website's styles do not affect it; server text is only ever set as text.
(function () {
	"use strict";
	var script = document.currentScript;
	if (!script || window.__reckonChat) return;
	window.__reckonChat = true;
	var site = (script.getAttribute("data-site") || new URL(script.src).origin).replace(/\/$/, "");
	var key = script.getAttribute("data-key") || "";
	var store = "reckon_chat_" + key;
	var api = site + "/api/method/reckon_sales_agent.api_channels.";
	var visitor = null;
	try { visitor = window.localStorage.getItem(store); } catch (err) { visitor = null; }
	var timer = null;
	var shown = 0;

	var host = document.createElement("div");
	host.style.cssText = "position:fixed;right:18px;bottom:18px;z-index:2147483000";
	document.body.appendChild(host);
	var root = host.attachShadow ? host.attachShadow({ mode: "open" }) : host;
	root.innerHTML = '<style>' +
		':host{all:initial}*{box-sizing:border-box;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}' +
		'.btn{width:56px;height:56px;border-radius:50%;border:0;background:#1f6feb;color:#fff;cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,.25);font-size:24px}' +
		'.box{display:none;position:absolute;right:0;bottom:70px;width:330px;max-width:calc(100vw - 36px);height:460px;max-height:calc(100vh - 110px);background:#fff;color:#1b1f24;border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.25);flex-direction:column;overflow:hidden}' +
		'.box.open{display:flex}.head{background:#1f6feb;color:#fff;padding:12px 14px;font-weight:600;display:flex;justify-content:space-between;align-items:center}' +
		'.x{background:none;border:0;color:#fff;font-size:20px;cursor:pointer}.log{flex:1;overflow:auto;padding:12px;display:flex;flex-direction:column;gap:8px;background:#f6f8fa}' +
		'.m{max-width:85%;padding:8px 11px;border-radius:12px;font-size:14px;line-height:1.4;white-space:pre-wrap;word-wrap:break-word}' +
		'.us{background:#fff;border:1px solid #e1e4e8;align-self:flex-start}.you{background:#1f6feb;color:#fff;align-self:flex-end}' +
		'.form{padding:10px;border-top:1px solid #e1e4e8;display:flex;flex-direction:column;gap:6px}' +
		'input,textarea{width:100%;border:1px solid #d0d7de;border-radius:8px;padding:8px;font-size:14px;color:#1b1f24;background:#fff}' +
		'textarea{resize:none;height:56px}.send{border:0;border-radius:8px;background:#1f6feb;color:#fff;padding:9px;font-size:14px;cursor:pointer}' +
		'.send:disabled{opacity:.6}.err{color:#c62828;font-size:12px;min-height:14px}.who{display:flex;gap:6px}' +
		'</style>' +
		'<div class="box" role="dialog" aria-label="Chat"><div class="head"><span class="title">Chat</span><button class="x" aria-label="Close">&times;</button></div>' +
		'<div class="log" aria-live="polite"></div><div class="form"><div class="who"><input class="name" placeholder="Your name" maxlength="80">' +
		'<input class="email" type="email" placeholder="Email" maxlength="140"></div><input class="phone" placeholder="Phone (optional)" maxlength="20">' +
		'<textarea class="text" placeholder="Write a message" maxlength="2000"></textarea><div class="err"></div><button class="send">Send</button></div></div>' +
		'<button class="btn" aria-label="Chat with us">&#128172;</button>';
	var $ = function (sel) { return root.querySelector(sel); };
	var box = $(".box"), log = $(".log"), err = $(".err"), send = $(".send");

	function bubble(text, who) {
		var div = document.createElement("div");
		div.className = "m " + who;
		div.textContent = text;
		log.appendChild(div);
	}

	function show(data) {
		if (data.title) $(".title").textContent = data.title;
		var messages = data.messages || [];
		if (messages.length < shown) shown = 0;
		if (!shown) {
			log.textContent = "";
			if (data.welcome) bubble(data.welcome, "us");
		}
		messages.slice(shown).forEach(function (m) { bubble(m.text || "", m.from === "you" ? "you" : "us"); });
		if (messages.length !== shown) log.scrollTop = log.scrollHeight;
		shown = messages.length;
		if (visitor) $(".who").style.display = $(".phone").style.display = "none";
	}

	function poll() {
		var url = api + "webchat_messages?key=" + encodeURIComponent(key) + (visitor ? "&visitor=" + encodeURIComponent(visitor) : "");
		return fetch(url, { credentials: "omit" }).then(function (r) { return r.json(); }).then(function (d) {
			if (d && d.ok) show(d);
		}).catch(function () {});
	}

	function open(on) {
		box.classList.toggle("open", on);
		clearInterval(timer);
		if (on) {
			poll();
			timer = setInterval(poll, 10000);
			$(".text").focus();
		}
	}

	$(".btn").addEventListener("click", function () { open(!box.classList.contains("open")); });
	$(".x").addEventListener("click", function () { open(false); });
	send.addEventListener("click", function () {
		var text = $(".text").value.trim();
		if (!text) return;
		var email = $(".email").value.trim(), phone = $(".phone").value.trim();
		if (!visitor && !email && !phone) { err.textContent = "Leave an email or phone so we can reply."; return; }
		err.textContent = "";
		send.disabled = true;
		fetch(api + "webchat_send", {
			method: "POST", credentials: "omit", headers: { "Content-Type": "text/plain" },
			body: JSON.stringify({ key: key, visitor: visitor, text: text, name: $(".name").value, email: email, phone: phone }),
		}).then(function (r) { return r.json(); }).then(function (d) {
			if (!d || !d.ok) { err.textContent = (d && d.error) || "Could not send; try again."; return; }
			visitor = d.visitor;
			try { window.localStorage.setItem(store, visitor); } catch (e2) { /* private mode: this visit only */ }
			$(".text").value = "";
			show(d);
		}).catch(function () { err.textContent = "Could not send; try again."; })
			.then(function () { send.disabled = false; });
	});
})();
