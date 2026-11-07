/* Reckon signup form: draws a form from its public key and sends the signup. No other script is needed.
 *
 * <script src="https://YOUR-SITE/assets/reckon_sales_agent/js/rsa_form.js" data-form="KEY" defer></script>
 *   data-mode   inline (default: shown where the script is) or popup
 *   data-target a CSS selector to draw an inline form into
 *   data-trigger / data-delay  popup: delay, scroll or exit (overrides the form's own settings)
 * The form is drawn inside a shadow root, so a website's styles never break it and it never changes the website's styles.
 */
(function () {
	"use strict";
	var script = document.currentScript;
	if (!script || !script.dataset.form) return;
	var slug = script.dataset.form, base = new URL(script.src).origin;
	var API = base + "/api/method/reckon_sales_agent.api_capture.";
	var HOUR = 3600 * 1000;

	function esc(v) { return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
	function remembered(key, set) {
		try { if (set) localStorage.setItem(key, String(Date.now())); else { var t = Number(localStorage.getItem(key) || 0); return t && Date.now() - t < 7 * 24 * HOUR; } } catch (e) { /* private window */ }
		return false;
	}

	var css = ":host{all:initial}*{box-sizing:border-box;font-family:system-ui,-apple-system,Segoe UI,sans-serif}" +
		".f{color:#1f2430;font-size:15px}.f h2{margin:0 0 6px;font-size:1.25rem}.f p{margin:0 0 12px;color:#4a5160;line-height:1.45}" +
		"label{display:block;margin:0 0 10px;font-size:.85rem;color:#4a5160}input[type=text],input[type=email],input[type=tel]{display:block;width:100%;margin-top:4px;padding:10px;border:1px solid #cdd2dc;border-radius:8px;font-size:1rem}" +
		".c{display:flex;gap:8px;align-items:flex-start;margin:0 0 10px;font-size:.85rem;color:#4a5160}.c input{margin-top:3px}" +
		"button{border:0;border-radius:8px;color:#fff;padding:11px 20px;font-size:1rem;cursor:pointer;width:100%}button[disabled]{opacity:.6;cursor:default}" +
		".e{color:#b3261e;font-size:.8rem;margin-top:3px}.ok{padding:14px;border-radius:8px;background:#eaf6ee;color:#1b5e20}.hp{position:absolute;left:-9999px;opacity:0;height:0;overflow:hidden}" +
		".o{position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:2147483000;padding:16px}" +
		".m{background:#fff;border-radius:12px;padding:24px;max-width:420px;width:100%;position:relative;box-shadow:0 10px 40px rgba(0,0,0,.25)}" +
		".x{position:absolute;top:8px;right:10px;background:none;color:#666;width:auto;font-size:1.4rem;padding:2px 8px}";

	function build(cfg, bare) {
		var fields = cfg.fields.map(function (f) {
			return '<label>' + esc(f.label) + (f.required ? " *" : "") + '<input type="' + esc(f.type) + '" name="' + esc(f.key) + '"' + (f.required ? " required" : "") +
				' autocomplete="' + (f.key === "email" ? "email" : f.key === "phone" ? "tel" : "off") + '"><span class="e" data-e="' + esc(f.key) + '"></span></label>';
		}).join("");
		var consent = cfg.consent_text ? '<div class="c"><input type="checkbox" name="consent" id="c1"' + (cfg.require_consent ? " required" : "") + '><label for="c1" style="margin:0">' + esc(cfg.consent_text) + '</label></div><span class="e" data-e="consent"></span>' : "";
		var sms = cfg.ask_sms ? '<div class="c"><input type="checkbox" name="sms_opt_in" id="c2"><label for="c2" style="margin:0">Text me updates (SMS)</label></div>' : "";
		var wa = cfg.ask_whatsapp ? '<div class="c"><input type="checkbox" name="whatsapp_opt_in" id="c3"><label for="c3" style="margin:0">Message me on WhatsApp</label></div>' : "";
		return '<div class="f">' + (bare ? "" : "<h2>" + esc(cfg.headline) + "</h2>" + (cfg.description ? "<p>" + esc(cfg.description) + "</p>" : "")) +
			'<form novalidate><div class="hp" aria-hidden="true"><input type="text" name="hp_website" tabindex="-1" autocomplete="off"></div>' + fields + consent + sms + wa +
			'<span class="e" data-e="form"></span><button type="submit" style="background:' + esc(cfg.accent) + '">' + esc(cfg.button) + "</button></form></div>";
	}

	function wire(root, cfg, done) {
		var form = root.querySelector("form");
		form.addEventListener("submit", function (ev) {
			ev.preventDefault();
			root.querySelectorAll(".e").forEach(function (n) { n.textContent = ""; });
			var body = new URLSearchParams(new FormData(form));
			body.set("slug", slug);
			form.querySelectorAll('input[type=checkbox]').forEach(function (c) { body.set(c.name, c.checked ? "1" : ""); });
			var button = form.querySelector("button");
			button.disabled = true;
			fetch(API + "submit", { method: "POST", body: body, credentials: "omit" })
				.then(function (r) { return r.json().then(function (j) { return j.message || j; }); })
				.then(function (res) {
					if (res.ok) {
						remembered("rsa_form_" + slug, true);
						if (res.redirect) { window.location.href = res.redirect; return; }
						form.outerHTML = '<div class="ok">' + esc(res.message || "Thank you!") + "</div>";
						if (done) done();
						return;
					}
					button.disabled = false;
					Object.keys(res.errors || {}).forEach(function (k) {
						var n = root.querySelector('[data-e="' + k + '"]');
						if (n) n.textContent = res.errors[k];
					});
				})
				.catch(function () { button.disabled = false; var n = root.querySelector('[data-e="form"]'); if (n) n.textContent = "Could not send. Please try again."; });
		});
	}

	function shadow(host, html, cfg) {
		var root = host.attachShadow({ mode: "open" });
		root.innerHTML = "<style>" + css + "</style>" + html;
		return root;
	}

	function inline(cfg) {
		var target = script.dataset.target ? document.querySelector(script.dataset.target) : null;
		var host = document.createElement("div");
		if (target) target.appendChild(host); else script.parentNode.insertBefore(host, script.nextSibling);
		wire(shadow(host, build(cfg, script.dataset.bare === "1"), cfg), cfg);
	}

	function popup(cfg) {
		if (remembered("rsa_form_" + slug)) return;
		var shown = false;
		function open() {
			if (shown) return;
			shown = true;
			var host = document.createElement("div");
			document.body.appendChild(host);
			var root = shadow(host, '<div class="o"><div class="m"><button class="x" aria-label="Close">&times;</button>' + build(cfg, false) + "</div></div>", cfg);
			function close() { remembered("rsa_form_" + slug, true); host.remove(); }
			root.querySelector(".x").addEventListener("click", close);
			root.querySelector(".o").addEventListener("click", function (e) { if (e.target.className === "o") close(); });
			document.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });
			wire(root, cfg, function () { setTimeout(close, 3500); });
		}
		var trigger = script.dataset.trigger || { "Scroll": "scroll", "Exit intent": "exit" }[cfg.popup_trigger] || "delay";
		if (trigger === "scroll") {
			window.addEventListener("scroll", function check() { if (window.scrollY > document.body.scrollHeight * 0.4) { window.removeEventListener("scroll", check); open(); } }, { passive: true });
		} else if (trigger === "exit") {
			document.addEventListener("mouseout", function (e) { if (!e.relatedTarget && e.clientY < 10) open(); });
		} else {
			setTimeout(open, Math.max(1, Number(script.dataset.delay || cfg.popup_delay || 8)) * 1000);
		}
	}

	fetch(API + "config?slug=" + encodeURIComponent(slug), { credentials: "omit" })
		.then(function (r) { return r.ok ? r.json() : null; })
		.then(function (j) {
			var cfg = j && (j.message || j);
			if (!cfg || !cfg.fields) return;
			(script.dataset.mode || (cfg.form_type === "Popup" ? "popup" : "inline")) === "popup" ? popup(cfg) : inline(cfg);
		})
		.catch(function () { /* the page keeps working without the form */ });
})();
