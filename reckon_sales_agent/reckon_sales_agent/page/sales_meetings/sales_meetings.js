// Meetings: demos the Meeting agent proposed, booked meetings, and outcomes to log.
// Wrapped in a closure: Desk evaluates page scripts in the global scope.
(() => {
	frappe.pages["sales-meetings"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Meetings"), single_column: true });
		page.add_inner_button(__("Agent Studio"), () => frappe.set_route("sales-agent"));
		page.add_inner_button(__("Conversations"), () => frappe.set_route("sales-inbox"));
		wrapper.meetings = new Meetings(page);
	};
	frappe.pages["sales-meetings"].on_page_show = (wrapper) => wrapper.meetings && wrapper.meetings.load();

	const API = "reckon_sales_agent.api_meetings.";
	const e = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const fmt = (v) => (v ? moment(v).format("ddd D MMM, h:mm A") : "");

	class Meetings {
		constructor(page) {
			this.page = page;
			this.$root = $('<div class="smt"></div>').appendTo(page.main);
		}

		load() {
			return frappe.xcall(API + "board").then((b) => this.render(b));
		}

		render(b) {
			const lead = (m) => `<b>${e(m.business || m.prospect)}</b>
				<div class="smt-muted">${[m.phone ? `<a href="tel:${e(m.phone)}">${e(m.phone)}</a>` : "", e(m.email || ""), e(m.assigned_to || "")]
					.filter(Boolean).join(" · ")}</div>`;
			const section = (key, title, sub, rows, body) => `<section class="smt-sec"><h3>${e(title)} <span>${rows.length}</span></h3>
				<div class="smt-muted">${e(sub)}</div>${rows.map((m) => `<div class="smt-card" data-m="${e(m.name)}">${body(m)}</div>`).join("")
					|| `<div class="smt-empty">${__("Nothing here.")}</div>`}</section>`;
			this.$root.html(
				section("book", __("To book"), __("The lead is interested. Pick the time they chose, or another."), b.to_book, (m) => `
					<div class="grow">${lead(m)}<div class="smt-muted">${e(m.source || "")}${m.invite_status ? ` · ${__("invitation")}: ${e(__(m.invite_status))}` : ""}</div></div>
					<div class="smt-slots">${m.slots.map((s) => `<button class="btn btn-xs btn-default smt-slot" data-s="${e(s)}">${e(fmt(s))}</button>`).join("")}
						<button class="btn btn-xs btn-default smt-other">${__("Other time")}</button></div>`)
				+ section("upcoming", __("Upcoming"), __("Booked demos. Reminders arrive a day and an hour before."), b.upcoming, (m) => `
					<div class="smt-when">${e(fmt(m.starts_on))}</div><div class="grow">${lead(m)}
					<div class="smt-muted">${e(m.mode || "")}${m.location ? ` · ${e(m.location)}` : ""}</div></div>
					<button class="btn btn-xs btn-default smt-other">${__("Reschedule")}</button>`)
				+ section("log", __("What happened?"), __("Meetings that have ended. A no-show gets new times offered."), b.to_log, (m) => `
					<div class="smt-when">${e(fmt(m.starts_on))}</div><div class="grow">${lead(m)}</div>
					<div class="smt-slots">${["Held", "No-show", "Cancelled"].map((o) => `<button class="btn btn-xs ${o === "Held" ? "btn-primary" : "btn-default"} smt-out" data-o="${o}">${__(o)}</button>`).join("")}</div>`)
				+ (b.done.length ? section("done", __("Recent"), "", b.done, (m) => `<div class="smt-when">${e(fmt(m.starts_on))}</div>
					<div class="grow">${lead(m)}<div class="smt-muted">${e(__(m.status))}${m.outcome_notes ? ` · ${e(m.outcome_notes)}` : ""}</div></div>`) : ""));
			this.$root.find(".smt-slot").on("click", (ev) => this.book($(ev.currentTarget).closest(".smt-card").data("m"), ev.currentTarget.dataset.s));
			this.$root.find(".smt-other").on("click", (ev) => {
				const m = $(ev.currentTarget).closest(".smt-card").data("m");
				frappe.prompt([{ fieldname: "starts_on", fieldtype: "Datetime", label: __("Starts on"), reqd: 1 }],
					(v) => this.book(m, v.starts_on), __("Choose a time"), __("Book"));
			});
			this.$root.find(".smt-out").on("click", (ev) => {
				const m = $(ev.currentTarget).closest(".smt-card").data("m");
				const result = ev.currentTarget.dataset.o;
				frappe.prompt([{ fieldname: "notes", fieldtype: "Small Text", label: __("Notes (what was agreed)") }],
					(v) => frappe.xcall(API + "outcome", { meeting: m, result, notes: v.notes }).then(() => {
						frappe.show_alert({ message: result === "No-show" ? __("New times proposed for approval") : __("Saved"), indicator: "green" });
						this.load();
					}), __(result), __("Save"));
			});
		}

		book(meeting, starts_on) {
			return frappe.xcall(API + "book", { meeting, starts_on }).then(() => {
				frappe.show_alert({ message: __("Booked: in the calendar with a CRM task"), indicator: "green" });
				this.load();
			});
		}
	}
})();
