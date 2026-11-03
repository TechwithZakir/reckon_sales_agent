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
	const MUTED_KEY = "rsa_muted";
	const muted = (prospect) => { try { return !!JSON.parse(localStorage.getItem(MUTED_KEY) || "{}")[prospect]; } catch (err) { return false; } };
	const set_muted = (prospect, on) => { try { const map = JSON.parse(localStorage.getItem(MUTED_KEY) || "{}"); if (on) map[prospect] = 1; else delete map[prospect]; localStorage.setItem(MUTED_KEY, JSON.stringify(map)); } catch (err) { /* private browsing */ } };
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
		#rsa-dock { position: fixed; left: 16px; bottom: 64px; z-index: 1030; font-size: 13px; line-height: 1.4; text-align: left; }
		#rsa-dock[hidden] { display: none; }
		#rsa-dock .rd-launch { border: 0; border-radius: 999px; padding: 9px 16px; background: #0084ff; color: #fff; font-weight: 600; box-shadow: 0 4px 14px rgba(0,0,0,.2); }
		#rsa-dock .rd-launch b { background: #fff; color: #0084ff; border-radius: 999px; padding: 0 7px; margin-left: 6px; }
		#rsa-dock .rd-panel { display: none; width: 340px; height: 470px; margin-bottom: 8px; text-align: left; flex-direction: column;
			background: #ffffff; color: #1f2937; border: 1px solid var(--border-color, #e3e5ea); border-radius: 14px; box-shadow: 0 8px 26px rgba(0,0,0,.2); overflow: hidden; }
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
		#rsa-dock .rd-composer { align-items: center; }
		#rsa-dock .rd-composer textarea { height: 34px; min-height: 34px; line-height: 20px; border-radius: 17px; padding: 6px 12px; }
		#rsa-dock .rd-channel { height: 34px; max-width: 104px; font-size: 12px; border-radius: 17px; }
		#rsa-dock .rd-send { width: 34px; height: 34px; border-radius: 50%; border: 0; background: #0084ff; color: #fff; flex: none; }
		#rsa-dock .rd-head { position: relative; }
		#rsa-dock .rd-more { border: 0; background: transparent; color: inherit; padding: 0 6px; border-radius: 6px; }
		#rsa-dock .rd-menu-pop { position: absolute; top: 46px; right: 10px; z-index: 2; min-width: 220px; padding: 6px;
			background: #ffffff; border: 1px solid #e3e5ea; border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,.2); text-align: left; }
		:root[data-theme="dark"] #rsa-dock .rd-menu-pop { background: #15132b; border-color: #374151; color: #e5e7eb; }
		#rsa-dock .rd-menu-pop[hidden] { display: none; }
		#rsa-dock .rd-menu-title { font-size: 11px; color: #8a8d91; padding: 6px 8px 2px; text-transform: uppercase; letter-spacing: .04em; }
		#rsa-dock .rd-menu-pop button { display: block; width: 100%; text-align: left; border: 0; background: transparent; color: inherit; padding: 6px 8px; border-radius: 8px; }
		#rsa-dock .rd-menu-pop button:hover { background: rgba(127,127,127,.15); }
		#rsa-dock .rd-menu-pop button.on { color: #0084ff; font-weight: 600; }
		#rsa-dock .rd-hint { color: #8a8d91; font-size: 12px; padding: 8px 10px; }
		#rsa-dock .rd-panel { background-color: #ffffff; opacity: 1; }
		:root[data-theme="dark"] #rsa-dock .rd-panel { background-color: #15132b; color: #e5e7eb; }
		@media (max-width: 480px) { #rsa-dock { left: 8px; right: 8px; bottom: 56px; }
			#rsa-dock .rd-panel { width: 100%; height: 62vh; } #rsa-dock .rd-launch { margin-left: auto; display: block; } }
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

	function minimize() { root().classList.remove("open"); }  // keeps the chat; the launch button brings it back
	function close_all() {  // forgets the open chat as well
		state.prospect = null;
		state.thread = null;
		store.set({});
		state.list = true;
		root().classList.remove("open");
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
				<button class="rd-min" aria-label="${esc(__("Minimize"))}" title="${esc(__("Minimize"))}">−</button><button class="rd-close" aria-label="${esc(__("Close"))}" title="${esc(__("Close"))}">×</button></div>
			<div class="rd-body">${rows || `<div class="rd-hint">${esc(__("No conversations yet."))}</div>`}</div>`;
		panel.querySelectorAll(".rd-row").forEach((row) => row.addEventListener("click", () => open_chat(row.dataset.p)));
		panel.querySelector(".rd-open").addEventListener("click", () => frappe.set_route("sales-inbox"));
		panel.querySelector(".rd-sound").addEventListener("click", () => { set_sound(!sound_on()); render_list(); });
		panel.querySelector(".rd-min").addEventListener("click", minimize);
		panel.querySelector(".rd-close").addEventListener("click", close_all);
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
				? `<div class="rd-composer"><select class="rd-channel">${open.map((ch) => `<option value="${esc(ch.channel)}">${esc(ch.channel)}</option>`).join("")}</select>
					<textarea class="rd-text" rows="1" placeholder="${esc(__("Write a reply…"))}"></textarea>
					<button class="rd-send" title="${esc(__("Send"))}">➤</button></div>`
				: `<div class="rd-hint">${esc(__("No channel to reply on right now"))}: ${esc(reason || "")}</div>`;
		panel.innerHTML = `
			<div class="rd-head"><button class="rd-back" aria-label="${esc(__("Back"))}">‹</button>
				<span class="rd-av">${esc(initials(name))}</span><span class="rd-title">${esc(name)}</span><button class="rd-more" aria-label="${esc(__("More"))}" title="${esc(__("More"))}">⌄</button><div class="rd-menu-pop" hidden><div class="rd-menu-title">${esc(__("AI reply"))}</div>${[["Company default", __("Use the Company setting")], ["Autopilot", __("AI replies on its own")], ["Suggest only", __("AI drafts, you approve")], ["Human only", __("Only you reply")]].map(([m, label]) => `<button class="rd-mode ${m === (t.conversation.ai_mode || "Company default") ? "on" : ""}" data-mode="${esc(m)}">${esc(label)}</button>`).join("")}<div class="rd-menu-title">${esc(__("Conversation"))}</div><button class="rd-mute">${esc(muted(state.prospect) ? __("Unmute notifications") : __("Mute notifications"))}</button><button class="rd-block">${esc(t.prospect.do_not_contact ? __("Unblock this lead") : __("Block this lead"))}</button><button class="rd-delete">${esc(__("Delete chat"))}</button><button class="rd-status">${esc(t.conversation.status === "Resolved" ? __("Reopen") : __("Resolve"))}</button><button class="rd-goto">${esc(__("Open in Conversations"))}</button></div>
				<button class="rd-open" title="${esc(__("Open Conversations"))}">↗</button>
				<button class="rd-min" aria-label="${esc(__("Minimize"))}" title="${esc(__("Minimize"))}">−</button><button class="rd-close" aria-label="${esc(__("Close"))}" title="${esc(__("Close"))}">×</button></div>
			<div class="rd-body">${messages || `<div class="rd-hint">${esc(__("No messages yet."))}</div>`}</div>
			${composer}`;
		const body = panel.querySelector(".rd-body");
		body.scrollTop = body.scrollHeight;
		panel.querySelector(".rd-back").addEventListener("click", () => { state.list = true; show_list(); });
		const pop = panel.querySelector(".rd-menu-pop");
		panel.querySelector(".rd-more").addEventListener("click", () => { pop.hidden = !pop.hidden; });
		pop.querySelectorAll(".rd-mode").forEach((btn) => btn.addEventListener("click", () => {
			call("set_mode", { prospect: state.prospect, mode: btn.dataset.mode }).then(() => open_chat(state.prospect));
		}));
		panel.querySelector(".rd-status").addEventListener("click", () => {
			call("set_status", { prospect: state.prospect, status: t.conversation.status === "Resolved" ? "Open" : "Resolved" })
				.then(() => open_chat(state.prospect));
		});
		panel.querySelector(".rd-goto").addEventListener("click", () => frappe.set_route("sales-inbox"));
		panel.querySelector(".rd-mute").addEventListener("click", () => { set_muted(state.prospect, !muted(state.prospect)); render_chat(); });
		panel.querySelector(".rd-block").addEventListener("click", () => {
			const blocking = !t.prospect.do_not_contact;
			const go = () => call("block", { prospect: state.prospect, blocked: blocking ? 1 : 0 }).then(() => open_chat(state.prospect));
			if (!blocking) return go();
			return frappe.confirm(__("Block this lead? We stop messaging them. You can unblock later."), go);
		});
		panel.querySelector(".rd-delete").addEventListener("click", () => frappe.confirm(
			__("Delete this chat? Its messages are removed for good. The lead itself stays."),
			() => call("delete_chat", { prospect: state.prospect }).then(() => { close_all(); return load_rows(); })));
		panel.querySelector(".rd-open").addEventListener("click", () => frappe.set_route("sales-inbox"));
		panel.querySelector(".rd-min").addEventListener("click", minimize);
		panel.querySelector(".rd-close").addEventListener("click", close_all);
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
		const fresh = rows.filter((r) => r.needs_reply && !muted(r.prospect) && (!(r.prospect in seen) || String(r.last) > String(seen[r.prospect])));
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

	// Sit to the right of Desk's sidebar, so the dock never covers the menu.
	function place() {
		const side = document.querySelector(".body-sidebar, .body-sidebar-container");
		const width = side ? side.getBoundingClientRect().width : 0;
		root().style.left = `${width + 16}px`;
	}

	function sync_visibility() {
		root().hidden = route_is_inbox() || !state.ready;
		place();
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
		$(window).on("resize", place);
	}

	$(document).ready(() => setTimeout(start, 500));
})();
