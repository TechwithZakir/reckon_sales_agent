// Meetings: what is coming, what needs you, a week view, every meeting in one table, and calendar links.
// Wrapped in a closure: Desk evaluates page scripts in the global scope.
(() => {
	frappe.pages["sales-meetings"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Meetings"), single_column: true });
		page.add_inner_button(__("Agent Studio"), () => frappe.set_route("sales-agent"));
		page.add_inner_button(__("Conversations"), () => frappe.set_route("sales-inbox"));
		wrapper.meetings = new Meetings(page);
		page.set_primary_action(__("New meeting"), () => wrapper.meetings.new_meeting(), "add");
	};
	frappe.pages["sales-meetings"].on_page_show = (wrapper) => wrapper.meetings && wrapper.meetings.load();

	const API = "reckon_sales_agent.api_meetings.";
	const e = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const fmt = (v) => (v ? moment(v).format("ddd D MMM, h:mm A") : "");
	const time = (v) => (v ? moment(v).format("h:mm A") : "");
	const num = (v) => Number(v || 0).toLocaleString();
	const STATUS_CLASS = { Proposed: "warn", Booked: "ok", Held: "ok", "No-show": "bad", Cancelled: "muted" };
	const VIEWS = [["agenda", __("Agenda")], ["week", __("Week")], ["all", __("All meetings")]];

	class Meetings {
		constructor(page) {
			this.page = page;
			this.view = "agenda";
			this.q = "";
			this.owner = "";
			this.week = moment().startOf("isoWeek");
			this.$root = $('<div class="smt"></div>').appendTo(page.main);
			this.$root.on("click", "[data-act]", (ev) => this.act(ev));
			// A click anywhere on a card opens its details; buttons and links inside keep their own action.
			this.$root.on("click", ".smt-card[data-m], .smt-day-item[data-m], .smt-row[data-m]", (ev) => {
				if (!$(ev.target).closest("a, button").length) this.details(ev.currentTarget.dataset.m);
			});
			this.$root.on("keydown", ".smt-card[data-m], .smt-day-item[data-m]", (ev) => {
				if ((ev.key === "Enter" || ev.key === " ") && ev.target === ev.currentTarget) { ev.preventDefault(); this.details(ev.currentTarget.dataset.m); }
			});
		}

		load() {
			return frappe.xcall(API + "board").then((b) => { this.b = b; this.render(); });
		}

		all() { return [...this.b.to_book, ...this.b.upcoming, ...this.b.to_log, ...this.b.done]; }

		find(name) { return this.all().find((m) => m.name === name); }

		// The owner and search choices narrow every list on the page.
		visible(m) {
			if (this.owner === "me" && m.assigned_to !== this.b.me) return false;
			if (this.owner && this.owner !== "me" && m.assigned_to !== this.owner) return false;
			const q = this.q.trim().toLowerCase();
			return !q || [m.business, m.prospect, m.phone, m.email, m.title, m.assigned_to, m.outcome_notes, m.source].join(" ").toLowerCase().includes(q);
		}

		render() {
			const b = this.b;
			const s = b.stats || {};
			const tile = (label, value, sub, view) => `<div class="smt-tile ${view ? "click" : ""}" ${view ? `data-act="view" data-view="${view}"` : ""}><span>${label}</span><b>${value}</b><span>${sub || "&nbsp;"}</span></div>`;
			this.$root.html(`
				<div class="smt-tiles">
					${tile(__("Today"), num(s.today), __("still to come"), "agenda")}
					${tile(__("Next 7 days"), num(s.week), __("booked"), "week")}
					${tile(__("To book"), num(s.to_book), __("interested leads"), "agenda")}
					${tile(__("Needs an outcome"), num(s.to_log), __("meetings that ended"), "agenda")}
					${tile(__("Held, 30 days"), num(s.held), s.no_show_rate == null ? __("no data yet") : __("{0}% did not happen", [s.no_show_rate]))}
				</div>
				<div class="smt-bar">
					<div class="smt-tabs" role="tablist">${VIEWS.map(([k, l]) => `<button type="button" class="smt-tab ${this.view === k ? "on" : ""}" data-act="view" data-view="${k}" role="tab" aria-selected="${this.view === k}">${e(l)}</button>`).join("")}</div>
					<input type="search" class="form-control input-sm smt-q" placeholder="${__("Search by lead, phone, email or note")}" value="${e(this.q)}" aria-label="${__("Search")}">
					<select class="form-control input-sm smt-owner" aria-label="${__("Whose meetings")}">
						<option value="">${__("Everyone")}</option><option value="me" ${this.owner === "me" ? "selected" : ""}>${__("Only mine")}</option>
						${b.owners.filter((o) => o !== b.me).map((o) => `<option value="${e(o)}" ${this.owner === o ? "selected" : ""}>${e(o)}</option>`).join("")}</select>
				</div>
				<div class="smt-body"></div>`);
			this.$root.find(".smt-q").on("input", frappe.utils.debounce((ev) => { this.q = ev.currentTarget.value; this.paint(); }, 200));
			this.$root.find(".smt-owner").on("change", (ev) => { this.owner = ev.currentTarget.value; this.paint(); });
			this.paint();
		}

		paint() {
			const $b = this.$root.find(".smt-body");
			if (this.view === "week") this.paint_week($b);
			else if (this.view === "all") this.paint_all($b);
			else this.paint_agenda($b);
			this.$root.find(".smt-tab").each((_, t) => $(t).toggleClass("on", t.dataset.view === this.view).attr("aria-selected", t.dataset.view === this.view));
		}

		// -------------------------------------------------------------- shared pieces
		lead(m) {
			const bits = [m.phone ? `<a href="tel:${e(m.phone)}">${e(m.phone)}</a>` : "", m.email ? `<a href="mailto:${e(m.email)}">${e(m.email)}</a>` : ""].filter(Boolean);
			return `<b>${e(m.business || m.prospect)}</b><div class="smt-muted">${bits.join(" · ")}${m.assigned_to ? `${bits.length ? " · " : ""}${e(m.assigned_to)}` : ""}</div>`;
		}

		where(m) {
			const link = m.meet_link || (/^https?:\/\//i.test(m.location || "") ? m.location : "");
			return [e(__(m.mode || "")), link ? `<a href="${e(link)}" target="_blank" rel="noopener noreferrer">${__("Join")}</a>` : e(m.location || ""),
				m.synced ? `<span class="smt-chip ok" title="${__("Also in the salesperson's Google Calendar")}">${__("Google Calendar")}</span>` : ""].filter(Boolean).join(" · ");
		}

		badge(m) { return `<span class="smt-chip ${STATUS_CLASS[m.status] || ""}">${e(__(m.status))}</span>`; }

		actions(m, kind) {
			if (kind === "book") {
				return `<div class="smt-slots">${m.slots.map((s) => `<button type="button" class="btn btn-xs btn-default" data-act="slot" data-s="${e(s)}">${e(fmt(s))}</button>`).join("")}
					<button type="button" class="btn btn-xs btn-default" data-act="other">${__("Other time")}</button></div>`;
			}
			if (kind === "log") {
				return `<div class="smt-slots">${["Held", "No-show", "Cancelled"].map((o) => `<button type="button" class="btn btn-xs ${o === "Held" ? "btn-primary" : "btn-default"}" data-act="out" data-o="${o}">${__(o)}</button>`).join("")}</div>`;
			}
			if (kind === "upcoming") {
				return `<div class="smt-slots"><button type="button" class="btn btn-xs btn-default" data-act="other">${__("Reschedule")}</button>
					<button type="button" class="btn btn-xs btn-default" data-act="cancel">${__("Cancel")}</button></div>`;
			}
			return "";
		}

		card(m, kind) {
			return `<div class="smt-card" data-m="${e(m.name)}" role="button" tabindex="0" aria-label="${e(__("Open {0}", [m.business || m.title]))}">
				<div class="smt-when">${m.starts_on ? `${e(time(m.starts_on))}<small>${e(moment(m.starts_on).format("ddd D MMM"))}</small>` : `<small>${__("No time yet")}</small>`}</div>
				<div class="grow">${this.lead(m)}<div class="smt-muted">${this.where(m)}${m.invite_status && kind === "book" ? ` · ${__("invitation")}: ${e(__(m.invite_status))}` : ""}</div></div>
				${this.actions(m, kind)}
				<button type="button" class="btn btn-xs btn-default" data-act="details">${__("Details")}</button></div>`;
		}

		section(title, sub, count, inner) {
			return `<section class="smt-sec"><h3>${e(title)} <span>${count}</span></h3>${sub ? `<div class="smt-muted">${e(sub)}</div>` : ""}${inner}</section>`;
		}

		// -------------------------------------------------------------- agenda
		paint_agenda($b) {
			const v = (list) => list.filter((m) => this.visible(m));
			const book = v(this.b.to_book), log = v(this.b.to_log), up = v(this.b.upcoming);
			const days = {};
			up.forEach((m) => {
				const key = moment(m.starts_on).format("YYYY-MM-DD");
				(days[key] = days[key] || []).push(m);
			});
			const label = (d) => (moment(d).isSame(moment(), "day") ? __("Today") : moment(d).isSame(moment().add(1, "day"), "day") ? __("Tomorrow") : moment(d).format("dddd D MMM"));
			$b.html(
				(book.length ? this.section(__("To book"), __("The lead is interested. Pick the time they chose, or another."), book.length, book.map((m) => this.card(m, "book")).join("")) : "")
				+ (log.length ? this.section(__("What happened?"), __("Meetings that have ended. A no-show gets new times offered."), log.length, log.map((m) => this.card(m, "log")).join("")) : "")
				+ this.section(__("Coming up"), __("Booked meetings by day. Reminders arrive a day and an hour before."), up.length,
					Object.keys(days).sort().map((d) => `<h4 class="smt-day">${e(label(d))} <span>${days[d].length}</span></h4>${days[d].map((m) => this.card(m, "upcoming")).join("")}`).join("")
					|| `<div class="smt-empty">${this.q || this.owner ? __("No meetings match.") : __("Nothing booked. Press New meeting, or wait for interested leads to appear above.")}</div>`));
		}

		// -------------------------------------------------------------- week
		paint_week($b) {
			const start = this.week.clone();
			const days = [...Array(7).keys()].map((i) => start.clone().add(i, "day"));
			const list = this.all().filter((m) => m.starts_on && this.visible(m));
			$b.html(`<div class="smt-weekbar"><button type="button" class="btn btn-xs btn-default" data-act="week" data-d="-1" aria-label="${__("Previous week")}">‹</button>
				<button type="button" class="btn btn-xs btn-default" data-act="week" data-d="0">${__("This week")}</button>
				<button type="button" class="btn btn-xs btn-default" data-act="week" data-d="1" aria-label="${__("Next week")}">›</button>
				<b>${e(start.format("D MMM"))} – ${e(start.clone().add(6, "day").format("D MMM YYYY"))}</b></div>
				<div class="smt-week">${days.map((d) => {
					const items = list.filter((m) => moment(m.starts_on).isSame(d, "day")).sort((a, b2) => (a.starts_on < b2.starts_on ? -1 : 1));
					return `<div class="smt-weekday ${d.isSame(moment(), "day") ? "today" : ""}"><h4>${e(d.format("ddd D"))}</h4>
						${items.map((m) => `<div class="smt-day-item ${STATUS_CLASS[m.status] || ""}" data-m="${e(m.name)}" role="button" tabindex="0"><b>${e(time(m.starts_on))}</b> ${e(m.business || m.title)}<small>${e(__(m.status))}</small></div>`).join("")
						|| `<div class="smt-empty">&nbsp;</div>`}</div>`;
				}).join("")}</div>`);
		}

		// -------------------------------------------------------------- all meetings (sort and pages)
		paint_all($b) {
			const rows = this.all().filter((m) => this.visible(m)).sort((a, b2) => String(b2.starts_on || "").localeCompare(String(a.starts_on || "")));
			$b.html(`<div class="smt-sec"><div class="smt-table-wrap"><table class="table smt-table"><thead><tr><th>${__("When")}</th><th>${__("Lead")}</th><th>${__("Status")}</th>
				<th>${__("Mode")}</th><th>${__("Owner")}</th><th>${__("Notes")}</th></tr></thead><tbody>
				${rows.map((m) => `<tr class="smt-row" data-m="${e(m.name)}"><td>${m.starts_on ? e(fmt(m.starts_on)) : "-"}</td>
					<td><a data-act="details" href="#">${e(m.business || m.prospect)}</a></td><td>${e(__(m.status))}</td><td>${e(__(m.mode || ""))}</td>
					<td>${e(m.assigned_to || "")}</td><td>${e((m.outcome_notes || "").slice(0, 80))}</td></tr>`).join("")
					|| `<tr><td colspan="6" class="smt-empty">${__("No meetings match.")}</td></tr>`}</tbody></table></div></div>`);
			if (window.rsa_tables) window.rsa_tables.enhance($b.find(".smt-table"), { size: 10, search: false });
		}

		// -------------------------------------------------------------- actions
		act(ev) {
			const $t = $(ev.currentTarget);
			const kind = $t.data("act");
			const name = $t.closest("[data-m]").data("m");
			ev.preventDefault();
			if (kind === "view") { this.view = $t.data("view"); this.render(); }
			else if (kind === "week") { const d = Number($t.data("d")); this.week = d ? this.week.clone().add(d, "week") : moment().startOf("isoWeek"); this.paint(); }
			else if (kind === "details") this.details(name);
			else if (kind === "slot") this.book(name, $t.data("s"));
			else if (kind === "other") this.pick_time(name);
			else if (kind === "out") this.outcome(name, $t.data("o"));
			else if (kind === "cancel") this.cancel(name);
		}

		done(msg) {
			frappe.show_alert({ message: msg, indicator: "green" });
			return this.load();
		}

		book(meeting, starts_on) {
			return frappe.xcall(API + "book", { meeting, starts_on }).then(() => this.done(__("Booked: in the calendar with a CRM task")));
		}

		pick_time(meeting) {
			frappe.prompt([{ fieldname: "starts_on", fieldtype: "Datetime", label: __("Starts on"), reqd: 1 }],
				(v) => this.book(meeting, v.starts_on), __("Choose a time"), __("Book"));
		}

		outcome(meeting, result) {
			frappe.prompt([{ fieldname: "notes", fieldtype: "Small Text", label: __("Notes (what was agreed)") }],
				(v) => frappe.xcall(API + "outcome", { meeting, result, notes: v.notes }).then(() => this.done(result === "No-show" ? __("New times proposed for approval") : __("Saved"))),
				__(result), __("Save"));
		}

		cancel(meeting) {
			frappe.confirm(__("Cancel this meeting? It leaves the calendar."), () => frappe.xcall(API + "cancel", { meeting }).then(() => this.done(__("Cancelled"))));
		}

		new_meeting() {
			const dialog = new frappe.ui.Dialog({
				title: __("New meeting"),
				fields: [
					{ fieldname: "prospect", fieldtype: "Link", options: "Sales Prospect", label: __("Lead"), reqd: 1 },
					{ fieldname: "agent", fieldtype: "Check", label: __("Let the agent propose three times and draft the invitation"), default: 0 },
					{ fieldname: "starts_on", fieldtype: "Datetime", label: __("Starts on"), depends_on: "eval:!doc.agent", mandatory_depends_on: "eval:!doc.agent" },
					{ fieldname: "mode", fieldtype: "Select", label: __("How"), options: "\nVideo call\nPhone\nIn person", depends_on: "eval:!doc.agent" },
					{ fieldname: "location", fieldtype: "Data", label: __("Link or place"), depends_on: "eval:!doc.agent" },
					{ fieldname: "notes", fieldtype: "Small Text", label: __("Note"), depends_on: "eval:!doc.agent" },
				],
				primary_action_label: __("Save"),
				primary_action: (v) => {
					const call = v.agent ? frappe.xcall(API + "propose", { prospect: v.prospect })
						: frappe.xcall(API + "schedule", { prospect: v.prospect, starts_on: v.starts_on, mode: v.mode || "", location: v.location || "", notes: v.notes || "" });
					call.then((r) => {
						dialog.hide();
						this.done(v.agent ? (r ? __("Times proposed: the invitation waits for your approval") : __("This lead already has an open meeting")) : __("Booked: in the calendar with a CRM task"));
					});
				},
			});
			dialog.show();
		}

		// -------------------------------------------------------------- details, with calendar links
		details(name) {
			const m = this.find(name);
			if (!m) return;
			const dialog = new frappe.ui.Dialog({ title: m.business || m.title, size: "large", fields: [{ fieldname: "body", fieldtype: "HTML" }] });
			const $w = dialog.fields_dict.body.$wrapper;
			const open = m.status === "Proposed" || m.status === "Booked";
			const ended = m.status === "Booked" && m.ends_on && moment(m.ends_on).isBefore(moment());
			$w.html(`<div class="smt"><div class="smt-detail">
				<div class="smt-bar"><div>${this.lead(m)}</div>${this.badge(m)}</div>
				<div class="smt-kv"><span>${__("When")}</span><b>${m.starts_on ? e(fmt(m.starts_on)) + (m.ends_on ? " – " + e(time(m.ends_on)) : "") : __("Not set yet")}</b></div>
				<div class="smt-kv"><span>${__("How")}</span><b>${this.where(m) || "-"}</b></div>
				<div class="smt-kv"><span>${__("From")}</span><b>${e(m.source || "-")}</b></div>
				<div class="smt-links">${m.prospect ? `<a class="btn btn-xs btn-default" href="/desk/sales-prospect/${encodeURIComponent(m.prospect)}">${__("Open lead")}</a>` : ""}
					${m.crm_lead ? `<a class="btn btn-xs btn-default" href="/crm/leads/${encodeURIComponent(m.crm_lead)}">${__("Open in CRM")}</a>` : ""}</div>
				${open && m.starts_on ? `<div class="smt-calendar"><h4>${__("Add to a calendar")}</h4><div class="smt-links smt-cal-links"><span class="smt-muted">${__("Loading…")}</span></div></div>` : ""}
				<h4>${__("Notes")}</h4><textarea class="form-control smt-notes" rows="3" placeholder="${__("What was agreed, or what to prepare")}">${e(m.outcome_notes || "")}</textarea>
				<div class="smt-links"><button type="button" class="btn btn-xs btn-default smt-save">${__("Save note")}</button>
					${m.status === "Booked" ? `<button type="button" class="btn btn-xs btn-default smt-resched">${__("Reschedule")}</button>` : ""}
					${open ? `<button type="button" class="btn btn-xs btn-default smt-cancel">${__("Cancel meeting")}</button>` : ""}
					${ended ? ["Held", "No-show"].map((o) => `<button type="button" class="btn btn-xs ${o === "Held" ? "btn-primary" : "btn-default"} smt-out" data-o="${o}">${__(o)}</button>`).join("") : ""}</div>
				<h4>${__("History")}</h4><div class="smt-timeline"><span class="smt-muted">${__("Loading…")}</span></div></div></div>`);
			$w.find(".smt-save").on("click", () => frappe.xcall(API + "save_notes", { meeting: m.name, notes: $w.find(".smt-notes").val() })
				.then(() => { frappe.show_alert({ message: __("Saved"), indicator: "green" }); this.load(); }));
			$w.find(".smt-resched").on("click", () => { dialog.hide(); this.pick_time(m.name); });
			$w.find(".smt-cancel").on("click", () => { dialog.hide(); this.cancel(m.name); });
			$w.find(".smt-out").on("click", (ev) => { dialog.hide(); this.outcome(m.name, ev.currentTarget.dataset.o); });
			frappe.xcall(API + "timeline", { meeting: m.name }).then((rows) => {
				$w.find(".smt-timeline").html(rows.map((r) => `<div class="smt-event"><div><b>${e(__(String(r.action).replace(/_/g, " ")))}</b>${r.summary ? `<div class="smt-muted">${e(r.summary)}</div>` : ""}</div>
					<span class="smt-muted">${e(frappe.datetime.prettyDate(r.creation))}</span></div>`).join("") || `<span class="smt-muted">${__("Nothing yet.")}</span>`);
			});
			if (open && m.starts_on) {
				frappe.xcall(API + "calendar", { meeting: m.name }).then((c) => {
					$w.find(".smt-cal-links").html(`<a class="btn btn-xs btn-default" href="${e(c.google)}" target="_blank" rel="noopener noreferrer">${__("Google Calendar")}</a>
						<a class="btn btn-xs btn-default" href="${e(c.office365)}" target="_blank" rel="noopener noreferrer">${__("Office 365")}</a>
						<a class="btn btn-xs btn-default" href="${e(c.outlook)}" target="_blank" rel="noopener noreferrer">${__("Outlook.com")}</a>
						<a class="btn btn-xs btn-default" href="${e(c.ics)}">${__("Download .ics (Apple, any app)")}</a>
						${c.event ? `<a class="btn btn-xs btn-default" href="/desk/event/${encodeURIComponent(c.event)}">${__("Open in Desk calendar")}</a>` : ""}
						<div class="smt-muted" style="width:100%">${m.synced ? __("This meeting is also in the salesperson's connected Google Calendar.") : __("Connect your Google Calendar in Desk (Google Calendar) and new meetings are added to it automatically.")}</div>`);
				}).catch(() => $w.find(".smt-cal-links").html(`<span class="smt-muted">${__("Calendar links are not available for this meeting.")}</span>`));
			}
			dialog.show();
		}
	}
})();
