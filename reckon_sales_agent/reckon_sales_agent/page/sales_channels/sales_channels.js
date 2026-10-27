// Channels: where leads reach the Company (email, WhatsApp, Messenger, Instagram, website chat) and the social
// pages the agents post to, each connected with the platform's own sign-in. Wrapped in a closure: Desk evaluates
// page scripts in the global scope.
(() => {
	frappe.pages["sales-channels"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Channels"), single_column: true });
		page.add_inner_button(__("Conversations"), () => frappe.set_route("sales-inbox"));
		page.add_inner_button(__("Agent Studio"), () => frappe.set_route("sales-agent"));
		wrapper.channels = new Channels(page);
	};
	frappe.pages["sales-channels"].on_page_show = (wrapper) => wrapper.channels && wrapper.channels.load();

	const API = "reckon_sales_agent.api_channels.";
	const e = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const PLATFORM_ICON = { "Facebook Page": "f", Instagram: "ig", LinkedIn: "in" };

	class Channels {
		constructor(page) {
			this.page = page;
			this.$root = $('<div class="sch"></div>').appendTo(page.main);
		}

		call(method, args) {
			return frappe.xcall(API + method, args || {});
		}

		load() {
			const params = new URLSearchParams(window.location.search);
			if (params.get("connected")) frappe.show_alert({ message: __("Connected {0} account(s).", [params.get("connected")]), indicator: "green" });
			if (params.get("connect_error")) frappe.msgprint({ title: __("Not connected"), message: e(params.get("connect_error")), indicator: "orange" });
			if (params.get("connected") || params.get("connect_error")) window.history.replaceState(null, "", window.location.pathname);
			return this.call("overview").then((d) => this.render(d));
		}

		render(d) {
			this.data = d;
			const status = (ok, on, off) => `<span class="sch-pill ${ok ? "ok" : ""}">${e(ok ? on : off)}</span>`;
			const social = (platforms) => d.accounts.filter((a) => platforms.includes(a.platform));
			this.$root.html(`
				${d.outbound_enabled ? "" : `<div class="sch-note">${__("Dry run is on: replies you approve are recorded but not delivered. Switch it off in Sales Agent Settings when you are ready.")}</div>`}
				<div class="sch-grid">
					<div class="sch-card">
						<div class="sch-head"><h3>${__("Email")}</h3>${status(d.email.account, __("Ready"), __("Not set up"))}</div>
						<p class="sch-muted">${d.email.account ? __("Replies go out from {0}.", [e(d.email.account)]) : __("Add an outgoing Email Account so the agents can send.")}</p>
						<a class="btn btn-default btn-xs" href="/desk/sales-templates">${__("Check email health")}</a>
					</div>
					<div class="sch-card">
						<div class="sch-head"><h3>WhatsApp</h3>${status(d.whatsapp.installed && d.whatsapp.enabled, __("On"), d.whatsapp.installed ? __("Off") : __("Not installed"))}</div>
						<p class="sch-muted">${d.whatsapp.installed
							? __("WhatsApp Business Cloud API through the Frappe WhatsApp app. Messages from leads open a conversation; replies inside 24 hours are free-form, later ones need an approved template.")
							: __("Ask your system provider to install the Frappe WhatsApp app (official WhatsApp Business Cloud API).")}</p>
					</div>
				</div>
				<div class="sch-card sch-fast">
					<div class="sch-head"><div><h3>${__("Fast answers")}</h3>
						<p class="sch-muted">${__("Chats go cold in minutes. Let the AI answer simple questions at once, turn buying comments into private chats, and get a reminder when someone waits.")}</p></div>
						${status(d.fast.auto_answer, __("Instant answers on"), __("Every reply waits for approval"))}</div>
					<div class="sch-form">
						<label class="sch-check"><input type="checkbox" class="sch-auto" ${d.fast.auto_answer ? "checked" : ""} ${d.can_manage ? "" : "disabled"}>
							${__("Answer simple chat questions at once (only facts from your approved knowledge; prices, discounts, complaints and anything unsure still wait for you)")}</label>
						<label class="sch-check"><input type="checkbox" class="sch-comments" ${d.fast.comment_to_chat ? "checked" : ""} ${d.can_manage ? "" : "disabled"}>
							${__("Answer buying comments (\"price?\", \"দাম কত?\") on our Facebook and Instagram posts with one private message")}</label>
						<label>${__("Remind {0} when a chat waits longer than (minutes; 0 = off)", [e(d.fast.assignee || __("the salesperson"))])}
							<input type="number" class="form-control sch-sla" min="0" max="1440" value="${e(d.fast.sla_minutes)}" ${d.can_manage ? "" : "disabled"}></label>
						${d.fast.assignee ? "" : `<div class="sch-muted">${__("Name the salesperson in Agent Studio → autopilot settings to receive reminders.")}</div>`}
						${d.can_manage ? `<div><button class="btn btn-default btn-sm sch-fast-save">${__("Save")}</button></div>` : ""}
					</div>
				</div>
				<div class="sch-card">
					<div class="sch-head"><div><h3>${__("Facebook, Instagram and Messenger")}</h3>
						<p class="sch-muted">${__("Sign in with Facebook to connect your Pages and the Instagram accounts linked to them. The agents can then publish approved posts, and messages to your Page or Instagram appear in Conversations.")}</p></div>
						${d.can_manage && d.meta_ready ? `<button class="btn btn-primary btn-sm sch-connect" data-provider="meta">${__("Connect with Facebook")}</button>` : ""}</div>
					${d.meta_ready ? "" : `<p class="sch-muted">${__("Your system provider has not set up the Meta app yet.")}</p>`}
					${this.accounts(social(["Facebook Page", "Instagram"]), true)}
					<div class="sch-muted">${__("Messages so far: Messenger {0} · Instagram {1}", [d.counts.Messenger, d.counts.Instagram])}</div>
				</div>
				<div class="sch-card">
					<div class="sch-head"><div><h3>LinkedIn</h3>
						<p class="sch-muted">${__("Sign in with LinkedIn to connect the company pages you administer, for approved posts.")}</p></div>
						${d.can_manage && d.linkedin_ready ? `<button class="btn btn-primary btn-sm sch-connect" data-provider="linkedin">${__("Connect with LinkedIn")}</button>` : ""}</div>
					${d.linkedin_ready ? "" : `<p class="sch-muted">${__("Your system provider has not set up the LinkedIn app yet.")}</p>`}
					${this.accounts(social(["LinkedIn"]), false)}
				</div>
				<div class="sch-card sch-webchat">
					<div class="sch-head"><div><h3>${__("Chat on your website")}</h3>
						<p class="sch-muted">${__("A chat button on your website. Visitors write; the AI drafts the answer and you approve it. They see replies in the chat.")}</p></div>
						${status(d.webchat.enabled, __("On"), __("Off"))}</div>
					<div class="sch-form">
						<label class="sch-check"><input type="checkbox" class="sch-wc-on" ${d.webchat.enabled ? "checked" : ""} ${d.can_manage ? "" : "disabled"}> ${__("Show the chat on our website")}</label>
						<label>${__("Title")}<input class="form-control sch-wc-title" maxlength="80" value="${e(d.webchat.title)}"></label>
						<label>${__("Welcome message")}<textarea class="form-control sch-wc-welcome" rows="2" maxlength="500">${e(d.webchat.welcome)}</textarea></label>
						<label>${__("Your websites (one per line; empty allows any)")}<textarea class="form-control sch-wc-origins" rows="2" placeholder="https://www.example.com">${e(d.webchat.origins)}</textarea></label>
						${d.can_manage ? `<div><button class="btn btn-default btn-sm sch-wc-save">${__("Save")}</button></div>` : ""}
					</div>
					${d.webchat.enabled && d.webchat.key ? `<p class="sch-muted">${__("Paste this before </body> on every page of your website:")}</p>
						<pre class="sch-code">${e(`<script src="${d.webchat.script}" data-site="${d.webchat.site}" data-key="${d.webchat.key}" defer></script>`)}</pre>
						<button class="btn btn-default btn-xs sch-copy">${__("Copy")}</button>
						<span class="sch-muted">${__("Chats so far: {0}", [d.counts["Web Chat"]])}</span>` : ""}
				</div>`);
			this.bind();
		}

		accounts(rows, messaging) {
			if (!rows.length) return `<div class="sch-muted sch-none">${__("Nothing connected yet.")}</div>`;
			const manage = this.data.can_manage;
			return `<div class="sch-accounts">${rows.map((a) => `
				<div class="sch-account ${a.last_error ? "bad" : ""}" data-name="${e(a.name)}">
					<span class="sch-badge">${e(PLATFORM_ICON[a.platform] || "")}</span>
					<div class="grow"><b>${e(a.account_name)}</b> <span class="sch-muted">${e(__(a.platform))}</span>
						<div class="sch-muted">${a.last_error ? e(a.last_error) : e(a.last_check || "")}${a.token_expires_on ? " · " + __("access ends {0}", [e(frappe.datetime.str_to_user(a.token_expires_on))]) : ""}</div></div>
					${messaging && a.platform !== "LinkedIn" ? `<label class="sch-check"><input type="checkbox" class="sch-msg" ${a.receive_messages ? "checked" : ""} ${manage ? "" : "disabled"}> ${__("Messages")}</label>` : ""}
					<label class="sch-check"><input type="checkbox" class="sch-on" ${a.enabled ? "checked" : ""} ${manage ? "" : "disabled"}> ${__("On")}</label>
					${manage ? `<button class="btn btn-default btn-xs sch-test">${__("Test")}</button>` : ""}
				</div>`).join("")}</div>`;
		}

		bind() {
			const r = this.$root;
			r.find(".sch-connect").on("click", (ev) => {
				$(ev.currentTarget).prop("disabled", true);
				this.call("social_connect", { provider: $(ev.currentTarget).data("provider") })
					.then((url) => (window.location.href = url))
					.catch(() => $(ev.currentTarget).prop("disabled", false));
			});
			const account = (ev) => $(ev.currentTarget).closest(".sch-account").data("name");
			r.find(".sch-on").on("change", (ev) => this.call("set_account", { account: account(ev), enabled: ev.currentTarget.checked ? 1 : 0 }).then((d) => this.render(d)));
			r.find(".sch-msg").on("change", (ev) => this.call("set_account", { account: account(ev), receive_messages: ev.currentTarget.checked ? 1 : 0 }).then((d) => this.render(d)));
			r.find(".sch-test").on("click", (ev) => this.call("check_account", { account: account(ev) }).then((d) => {
				this.render(d);
				frappe.show_alert({ message: __("Checked"), indicator: "blue" });
			}));
			const save_chat = () => this.call("set_webchat", { data: JSON.stringify({
				enabled: r.find(".sch-wc-on").is(":checked") ? 1 : 0, title: r.find(".sch-wc-title").val(),
				welcome: r.find(".sch-wc-welcome").val(), origins: r.find(".sch-wc-origins").val(),
			}) }).then((d) => {
				this.render(d);
				frappe.show_alert({ message: __("Website chat saved"), indicator: "green" });
			});
			r.find(".sch-wc-save").on("click", save_chat);
			r.find(".sch-wc-on").on("change", save_chat);
			r.find(".sch-fast-save").on("click", () => this.call("set_fast_answers", { data: JSON.stringify({
				auto_answer: r.find(".sch-auto").is(":checked") ? 1 : 0, comment_to_chat: r.find(".sch-comments").is(":checked") ? 1 : 0,
				sla_minutes: Number(r.find(".sch-sla").val() || 0),
			}) }).then((d) => {
				this.render(d);
				frappe.show_alert({ message: __("Fast answers saved"), indicator: "green" });
			}));
			r.find(".sch-copy").on("click", () => frappe.utils.copy_to_clipboard(r.find(".sch-code").text()));
		}
	}
})();
