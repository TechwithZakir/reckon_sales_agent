// Conversation dock: a Messenger-style chat that stays open while you move between Desk pages.
// Loaded once per Desk session (app_include_js), so it keeps running as the Desk changes pages. It uses the same
// conversation API as the Conversations page and updates live over the same realtime event.
(() => {
	const API = "reckon_sales_agent.api_conversations.";
	const EVENT = "rsa_inbox";
	const KEY = "rsa_dock";
	const state = { rows: [], prospect: null, thread: null, list: true, ready: false, primed: false };
	const seen = {};  // prospect -> the last message time we have already announced
	const SOUND_KEY = "rsa_sound";
	const sound_on = () => { try { return localStorage.getItem(SOUND_KEY) !== "off"; } catch (err) { return true; } };
	const set_sound = (on) => { try { localStorage.setItem(SOUND_KEY, on ? "on" : "off"); } catch (err) { /* private browsing */ } };
	const ring = () => { try { frappe.utils.play_sound("notification"); } catch (err) { /* no audio here */ } };

	const store = {
		get() { try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (err) { return {}; } },
		set(value) { try { localStorage.setItem(KEY, JSON.stringify(value)); } catch (err) { /* private browsing */ } },
	};
	const call = (method, args) => frappe.xcall(API + method, args || {});
	const esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
	const ago = (value) => (value ? frappe.datetime.prettyDate(value) : "");
	const initials = (name) => (String(name || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("") || "?").toUpperCase();
	const waiting = () => state.rows.filter((r) => r.needs_reply).length;

	const STYLE = `
		#rsa-dock { position: fixed; right: 16px; bottom: 16px; z-index: 1030; font-size: 13px; line-height: 1.4; text-align: right; }
		#rsa-dock[hidden] { display: none; }
		#rsa-dock .rd-launch { border: 0; border-radius: 999px; padding: 9px 16px; background: #0084ff; color: #fff; font-weight: 600; box-shadow: 0 4px 14px rgba(0,0,0,.2); }
		#rsa-dock .rd-launch b { background: #fff; color: #0084ff; border-radius: 999px; padding: 0 7px; margin-left: 6px; }
		#rsa-dock .rd-panel { display: none; width: 340px; height: 470px; margin-bottom: 8px; text-align: left; flex-direction: column;
			background: var(--card-bg, #fff); color: var(--text-color, #1f2937); border: 1px solid var(--border-color, #e3e5ea); border-radius: 14px; box-shadow: 0 8px 26px rgba(0,0,0,.2); overflow: hidden; }
		#rsa-dock.open .rd-panel { display: flex; }
		#rsa-dock .rd-head { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--border-color, #e3e5ea); }
		#rsa-dock .rd-head .rd-title { flex: 1; min-width: 0; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
		#rsa-dock .rd-head button { border: 0; background: transparent; color: inherit; padding: 2px 6px; border-radius: 6px; }
		#rsa-dock .rd-head button:hover { background: rgba(127,127,127,.15); }
		#rsa-dock .rd-av { width: 32px; height: 32px; border-radius: 50%; background: #0084ff; color: #fff; display: flex; align-items: center; justify-content: center; font-weight: 600; flex: none; font-size: 12px; }
		#rsa-dock .rd-body { flex: 1; overflow: auto; padding: 8px 10px; }
		#rsa-dock .rd-row { display: flex; align-items: center; gap: 10px; padding: 8px; border-radius: 10px; cursor: pointer; }
		#rsa-dock .rd-row:hover { background: rgba(127,127,127,.12); }
		#rsa-dock .rd-row .rd-name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
		#rsa-dock .rd-row .rd-sub { color: #8a8d91; font-size: 11.5px; }
		#rsa-dock .rd-pill { font-size: 10.5px; border-radius: 999px; padding: 1px 7px; background: rgba(0,132,255,.15); color: #0084ff; }
		#rsa-dock .rd-sep { text-align: center; font-size: 11px; color: #8a8d91; margin: 10px 0 4px; }
		#rsa-dock .rd-bub-row { display: flex; margin: 2px 0; }
		#rsa-dock .rd-bub-row.out { justify-content: flex-end; }
		#rsa-dock .rd-bub { max-width: 76%; padding: 7px 12px; border-radius: 18px; white-space: pre-wrap; word-break: break-word; }
		#rsa-dock .rd-in .rd-bub { background: var(--control-bg, #e4e6eb); color: var(--text-color, #050505); border-bottom-left-radius: 6px; }
		#rsa-dock .rd-out .rd-bub { background: #0084ff; color: #fff; border-bottom-right-radius: 6px; }
		#rsa-dock .rd-note { text-align: center; color: #8a8d91; font-size: 11.5px; margin: 6px 0; }
		#rsa-dock .rd-composer { display: flex; gap: 6px; align-items: flex-end; padding: 8px; border-top: 1px solid var(--border-color, #e3e5ea); }
		#rsa-dock .rd-composer textarea { flex: 1; resize: none; border-radius: 18px; min-height: 36px; max-height: 96px; padding: 7px 12px; }
		#rsa-dock .rd-composer select { max-width: 120px; font-size: 12px; }
		#rsa-dock .rd-hint { color: #8a8d91; font-size: 12px; padding: 8px 10px; }
		@media (max-width: 480px) { #rsa-dock .rd-panel { width: calc(100vw - 32px); height: 60vh; } }
	`;

	function root() {
		let el = document.getElementById("rsa-dock");
		if (el) return el;
		const style = document.createElement("style");
		style.textContent = STYLE;
		document.head.appendChild(style);
		el = document.createElement("div");
		el.id = "rsa-dock";
		el.hidden = true;
		el.innerHTML = `<div class="rd-panel"></div><button class="rd-launch" type="button"></button>`;
		document.body.appendChild(el);
		el.querySelector(".rd-launch").addEventListener("click", () => {
			el.classList.toggle("open");
			if (el.classList.contains("open") && !state.prospect) show_list();
		});
		return el;
	}

	function launch_label() {
		const count = waiting();
		return `${frappe.utils.escape_html(__("Conversations"))}${count ? `<b>${count}</b>` : ""}`;
	}

	function render_launch() {
		const el = root();
		el.querySelector(".rd-launch").innerHTML = launch_label();
	}

	function show_list() {
		state.prospect = null;
		state.thread = null;
		store.set({});
		state.list = true;
		render_list();
	}

	function render_list() {
		const panel = root().querySelector(".rd-panel");
		const rows = state.rows.slice(0, 40).map((r) => `
			<div class="rd-row" data-p="${esc(r.prospect)}">
				<span class="rd-av">${esc(initials(r.business))}</span>
				<div style="min-width:0;flex:1">
					<div class="rd-name">${esc(r.business || r.prospect)}</div>
					<div class="rd-sub">${esc(ago(r.last))}${r.needs_reply ? ` · <span class="rd-pill">${esc(__("They spoke last"))}</span>` : ""}</div>
				</div></div>`).join("");
		panel.innerHTML = `
			<div class="rd-head"><span class="rd-title">${esc(__("Conversations"))}</span>
				<button class="rd-sound" title="${esc(__("New message sound"))}">${sound_on() ? "🔔" : "🔕"}</button>
				<button class="rd-open" title="${esc(__("Open Conversations"))}">↗</button>
				<button class="rd-close" aria-label="${esc(__("Close"))}">×</button></div>
			<div class="rd-body">${rows || `<div class="rd-hint">${esc(__("No conversations yet."))}</div>`}</div>`;
		panel.querySelectorAll(".rd-row").forEach((row) => row.addEventListener("click", () => open_chat(row.dataset.p)));
		panel.querySelector(".rd-open").addEventListener("click", () => frappe.set_route("sales-inbox"));
		panel.querySelector(".rd-sound").addEventListener("click", () => { set_sound(!sound_on()); render_list(); });
		panel.querySelector(".rd-close").addEventListener("click", () => root().classList.remove("open"));
	}

	function open_chat(prospect) {
		state.prospect = prospect;
		store.set({ prospect });
		return call("thread", { prospect }).then((thread) => {
			state.thread = thread;
			render_chat();
		});
	}

	function render_chat() {
		const t = state.thread;
		if (!t) return;
		const panel = root().querySelector(".rd-panel");
		const name = t.prospect.business_name || state.prospect;
		const open = (t.channels || []).filter((ch) => ch.ok);
		const reason = (t.channels || []).filter((ch) => !ch.ok).map((ch) => `${ch.channel}: ${ch.reason}`).join(" · ");
		let last_day = "";
		const messages = (t.timeline || []).map((item) => {
			const day = item.at ? String(item.at).slice(0, 10) : "";
			const sep = day && day !== last_day ? `<div class="rd-sep">${esc(frappe.datetime.str_to_user(day))}</div>` : "";
			last_day = day || last_day;
			if (item.direction === "note") return `${sep}<div class="rd-note">${esc(item.text || item.status)}</div>`;
			const side = item.direction === "out" ? "out" : "in";
			return `${sep}<div class="rd-bub-row ${side === "out" ? "out" : ""}"><div class="rd-${side}"><div class="rd-bub">${esc(item.text)}</div>
				<div class="rd-meta" style="font-size:11px;color:#8a8d91">${esc(item.channel || "")} · ${esc(ago(item.at))}</div></div></div>`;
		}).join("");
		const composer = t.prospect.do_not_contact
			? `<div class="rd-hint">${esc(__("This lead asked not to be contacted."))}</div>`
			: open.length
				? `<div class="rd-composer"><select class="form-control rd-channel">${open.map((ch) => `<option value="${esc(ch.channel)}">${esc(ch.channel)}</option>`).join("")}</select>
					<textarea class="form-control rd-text" rows="1" placeholder="${esc(__("Write a reply…"))}"></textarea>
					<button class="btn btn-primary btn-sm rd-send">${esc(__("Send"))}</button></div>`
				: `<div class="rd-hint">${esc(__("No channel to reply on right now"))}: ${esc(reason || "")}</div>`;
		panel.innerHTML = `
			<div class="rd-head"><button class="rd-back" aria-label="${esc(__("Back"))}">‹</button>
				<span class="rd-av">${esc(initials(name))}</span><span class="rd-title">${esc(name)}</span>
				<button class="rd-open" title="${esc(__("Open Conversations"))}">↗</button>
				<button class="rd-close" aria-label="${esc(__("Close"))}">×</button></div>
			<div class="rd-body">${messages || `<div class="rd-hint">${esc(__("No messages yet."))}</div>`}</div>
			${composer}`;
		const body = panel.querySelector(".rd-body");
		body.scrollTop = body.scrollHeight;
		panel.querySelector(".rd-back").addEventListener("click", () => { state.list = true; show_list(); });
		panel.querySelector(".rd-open").addEventListener("click", () => frappe.set_route("sales-inbox"));
		panel.querySelector(".rd-close").addEventListener("click", () => root().classList.remove("open"));
		const send = panel.querySelector(".rd-send");
		if (send) send.addEventListener("click", () => send_reply(panel));
		const text = panel.querySelector(".rd-text");
		if (text) text.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) send_reply(panel); });
	}

	function send_reply(panel) {
		const text = panel.querySelector(".rd-text").value.trim();
		if (!text) return;
		const channel = panel.querySelector(".rd-channel").value;
		panel.querySelector(".rd-send").disabled = true;
		call("send", { prospect: state.prospect, channel, text })
			.then(() => open_chat(state.prospect))
			.catch(() => {})  // the server already showed the reason
			.finally(() => { const btn = panel.querySelector(".rd-send"); if (btn) btn.disabled = false; });
	}

	// A bell when a lead writes in: a lead that needs a reply and has a newer message than we announced before.
	// The first load only records what is already there, so opening a page never rings.
	function announce(rows) {
		const fresh = rows.filter((r) => r.needs_reply && (!(r.prospect in seen) || String(r.last) > String(seen[r.prospect])));
		rows.forEach((r) => { seen[r.prospect] = r.last; });
		if (state.primed && fresh.length && sound_on()) ring();
		state.primed = true;
	}

	function load_rows() {
		return call("threads").then((rows) => {
			state.rows = rows || [];
			announce(state.rows);
			render_launch();
			if (root().classList.contains("open") && state.list && !state.prospect) render_list();
		});
	}

	function on_realtime(data) {
		load_rows();
		if (state.prospect && data && data.prospect === state.prospect) open_chat(state.prospect);
	}

	function route_is_inbox() {
		return (frappe.get_route() || [])[0] === "sales-inbox";  // the full page is open: no need for the dock
	}

	function sync_visibility() {
		root().hidden = route_is_inbox() || !state.ready;
	}

	function start() {
		if (state.ready || !frappe.session || frappe.session.user === "Guest") return;
		load_rows().then(() => {
			state.ready = true;
			const saved = store.get().prospect;
			if (saved) {
				root().classList.add("open");
				open_chat(saved);
			}
			sync_visibility();
		}).catch(() => { state.ready = false; });  // no access to conversations for this user: stay hidden
		frappe.realtime.on(EVENT, frappe.utils.debounce(on_realtime, 300));
		setInterval(() => { if (state.ready) load_rows(); }, 60000);
		$(document).on("page-change", sync_visibility);
	}

	$(document).ready(() => setTimeout(start, 500));
})();
