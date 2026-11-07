/* Friendlier technical lists and a first-login tour for the Sales Agent.
 *
 * 1. Each list under "Advanced" gets one plain sentence saying what it is and when to look at it, and the system "ID" column
 *    is hidden so people see names instead of codes.
 * 2. A short guided tour runs once for each person on their first visit; it can be replayed from the Help dialog.
 * 3. Items that only the system provider needs (marked "(vendor)") are hidden from everyone else.
 *
 * All of it is a convenience: every part is wrapped so a failure here can never break a page.
 */
(function () {
	"use strict";
	if (!window.frappe) return;

	const INTRO = {
		"Sales Prospect": __("Every business or person the agents have found, with how well they fit. Most people work from “Review new leads” instead."),
		"Sales Outreach Message": __("Each message the agents drafted or sent, and whether a person approved it."),
		"Sales Suppression Entry": __("People who must never be contacted. Add someone here and they are skipped everywhere."),
		"Sales Capture Form": __("Your signup forms. Change them from “Signup forms and lists”; this list is only for finding one quickly."),
		"Sales Segment": __("Saved groups of people made by rules. They update themselves."),
		"Sales Audience": __("The groups of people campaigns are sent to."),
		"Sales Campaign": __("Every campaign and where it stands. Open “Campaigns” for the friendlier view."),
		"Sales Campaign Member": __("Who is inside each campaign and how far they have got."),
		"Sales Communication Event": __("Everything that happened to a message: delivered, opened, clicked, replied, bounced."),
		"Sales Campaign Insight": __("Advice the AI gave on how to improve a campaign. You decide whether to use it."),
		"Sales Business Profile": __("What your business sells and to whom. The agents read this before they write anything."),
		"Sales Market Brief": __("Short market research notes the AI wrote about the kind of customers you want."),
		"Sales Targeting Profile": __("A description of your ideal customer used to search for leads."),
		"Sales Discovery Campaign": __("Saved lead searches. Each one says what to look for and where."),
		"Sales Research Report": __("What the agent learned about a lead from its website and other public sources."),
		"Sales Qualification": __("The score the agent gave each lead, and why."),
		"Sales Discovery Job": __("Searches running or finished in the background. Look here if a search seems stuck."),
		"Sales Knowledge Item": __("Facts about your business that the AI is allowed to use in messages and replies."),
		"Sales Social Post": __("Social media posts waiting for approval or already published."),
		"Sales Social Account": __("The Facebook, Instagram and LinkedIn accounts connected to this tool."),
		"Sales Qualification Profile": __("The rules used to score leads. Change these only if scores feel wrong."),
		"Sales Source Connector": __("Where leads are searched for. Your system provider switches these on."),
		"Sales Usage Ledger": __("What you have used this month against your plan limits."),
		"Sales Agent Activity": __("A record of what every AI agent did and who approved it. Useful for audits."),
		"Sales Provider Usage": __("Platform use of outside services, for the system provider."),
	};

	Object.keys(INTRO).forEach((dt) => {
		try {
			const prev = (frappe.listview_settings[dt] = frappe.listview_settings[dt] || {});
			const onload = prev.onload;
			prev.hide_name_column = true;
			prev.onload = function (lv) {
				if (onload) onload.call(this, lv);
				try {
					const root = lv.page && lv.page.wrapper;
					if (!root || $(root).find(".rsa-list-intro").length) return;
					$(root).find(".layout-main-section").first().before(
						`<div class="rsa-list-intro" style="margin:0 0 10px;padding:8px 12px;border-radius:8px;background:var(--bg-light-gray,#f3f4f6);font-size:13px;color:var(--text-muted)">${frappe.utils.escape_html(INTRO[dt])}</div>`
					);
				} catch (err) { /* no intro is fine */ }
			};
		} catch (err) { /* keep going */ }
	});

	// ----- vendor-only items -----
	const roles = () => (frappe.boot && frappe.boot.user && frappe.boot.user.roles) || [];
	const is_vendor = () => roles().some((r) => r === "System Manager" || r === "Reckon Vendor Superuser");

	function hide_vendor_items() {
		try {
			if (is_vendor()) return;
			document.querySelectorAll(".sidebar-item-container, .standard-sidebar-item, .sidebar-item-label").forEach((el) => {
				if (/\(vendor\)/i.test(el.textContent || "")) {
					const row = el.closest(".sidebar-item-container") || el;
					if (row.querySelector(".sidebar-item-container")) return;  // a parent holding other items: leave it
					row.style.display = "none";
				}
			});
		} catch (err) { /* ignore */ }
	}

	// ----- first-login tour -----
	const STEPS = [
		{ title: __("Welcome to your AI sales team"), body: __("This short tour shows where things are. It takes under a minute and you will only see it once.") },
		{ title: __("Get started"), body: __("The first item in the left menu is a checklist. Most steps are done for you; check them and fix anything marked To do.") },
		{ title: __("Find customers"), body: __("Say who you sell to. The agent finds businesses, researches them and scores how well they fit. You approve the good ones under “Review new leads”.") },
		{ title: __("Reach out"), body: __("Campaigns, signup forms and automations send messages. Nothing reaches a customer until a person approves it.") },
		{ title: __("Inbox and Meetings"), body: __("Replies from customers land in the Inbox with a suggested answer. Interested people can be booked into Meetings.") },
		{ title: __("Need help?"), body: __("Press Help at the top of any page for a short guide in plain words. You can replay this tour from there.") },
	];

	function run_tour(force) {
		try {
			if (!force && localStorage.getItem("rsa_tour_done")) return;
		} catch (err) { if (!force) return; }
		let i = 0;
		const d = new frappe.ui.Dialog({ title: STEPS[0].title, fields: [{ fieldtype: "HTML", fieldname: "body" }] });
		const draw = () => {
			const s = STEPS[i];
			d.set_title(s.title);
			d.fields_dict.body.$wrapper.html(`<p style="font-size:14px;line-height:1.55;margin:0 0 6px">${frappe.utils.escape_html(s.body)}</p>
				<p class="text-muted" style="font-size:12px;margin:0">${__("Step {0} of {1}", [i + 1, STEPS.length])}</p>`);
			d.set_primary_action(i === STEPS.length - 1 ? __("Done") : __("Next"), () => {
				if (i === STEPS.length - 1) { d.hide(); return; }
				i += 1; draw();
			});
			d.set_secondary_action_label && d.set_secondary_action_label(__("Skip"));
		};
		d.set_secondary_action && d.set_secondary_action(() => d.hide());
		d.onhide = () => { try { localStorage.setItem("rsa_tour_done", "1"); } catch (err) { /* ignore */ } };
		draw();
		d.show();
	}
	window.rsa_run_tour = () => run_tour(true);

	function on_route() {
		hide_vendor_items();
		try {
			const route = frappe.get_route() || [];
			const mine = ["sales-setup", "sales-agent", "sales-inbox", "lead-finder", "sales-review", "campaign-studio"].includes(route[0]);
			if (mine) setTimeout(() => run_tour(false), 1500);
		} catch (err) { /* ignore */ }
	}

	if (frappe.router) frappe.router.on("change", () => { setTimeout(on_route, 700); setTimeout(hide_vendor_items, 2500); });
	$(document).ready(() => setTimeout(on_route, 1800));
})();
