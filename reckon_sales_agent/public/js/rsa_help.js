/* Help for people who are not technical: a "Help" button on every Sales Agent page.
 *
 * It opens a short guide in plain words: what the page is for, what to do first, and what the words on it mean. Nothing here
 * talks to the server, and a failure here must never break a page, so everything is wrapped and skipped quietly.
 */
(function () {
	"use strict";
	if (!window.frappe || !frappe.router) return;

	const e = (v) => frappe.utils.escape_html(String(v == null ? "" : v));

	// route name -> guide. Written for a business owner or a salesperson, not for an engineer.
	const GUIDE = {
		"sales-setup": { title: __("Get started"), purpose: __("A short checklist that sets the AI sales team up for your business. Most steps are done for you; check them and fix anything that is wrong."),
			steps: [__("Go down the list from the top. Each step says what it is for."), __("Anything marked To do needs you."), __("You can change every answer later.")] },
		"sales-agent": { title: __("Home"), purpose: __("Your day at a glance: what needs you, how many leads you have found and contacted, and what the AI agents have been doing."),
			steps: [__("Start with “Needs you today”: leads to review, replies to answer, messages to approve."), __("Open “See what each AI agent is doing” if you are curious."), __("Nothing is sent to a customer until you approve it, unless you switch autopilot on.")] },
		"sales-inbox": { title: __("Inbox"), purpose: __("Every conversation with your leads in one place: email, WhatsApp, Messenger and website chat."),
			steps: [__("Open a conversation to read it and the AI’s suggested answer."), __("Send the answer, edit it, or take over."), __("Resolve a conversation when it is done.")] },
		"sales-meetings": { title: __("Meetings"), purpose: __("Meetings the agents are arranging with interested leads."),
			steps: [__("Check proposed times before they are sent."), __("Confirm a booked meeting and it goes in the calendar.")] },
		"lead-finder": { title: __("Find customers"), purpose: __("Describe who you sell to and the agent finds businesses, researches them and scores how well they fit."),
			steps: [__("Pick where to look. Smart Sources is the easiest choice."), __("Say what kind of business and where."), __("Press Launch. New leads appear under “Review new leads”.")] },
		"sales-review": { title: __("Review new leads"), purpose: __("The leads the agent found. You decide who is worth contacting."),
			steps: [__("Approve the good ones, reject the rest."), __("The AI’s suggestion and its reason are shown; you have the last word."), __("Only approved leads can be contacted.")] },
		"campaign-studio": { title: __("Campaigns"), purpose: __("Send a message or a series of messages to a group of people, and see what they do with it."),
			steps: [__("Press New campaign and pick what you want to do."), __("Choose who gets it (an audience) and which message templates to use."), __("Submit it. A manager approves, then it starts."), __("Watch the results on the campaign page.")] },
		"capture-studio": { title: __("Signup forms and lists"), purpose: __("Collect people who want to hear from you, keep your lists clean and connect other systems."),
			steps: [__("Forms: make a signup form and share its link or put it on your website."), __("Segments: save a group of people by rules, such as “opened an email this month”."), __("Import: bring in a list from a spreadsheet."), __("Clean list: find addresses that will bounce."), __("Developers: for your technical team.")] },
		"automation-studio": { title: __("Automations"), purpose: __("Messages that follow people automatically: welcome new signups, follow up if they did not open, tag the interested ones."),
			steps: [__("Press New automation and start from a ready-made flow."), __("Click a step to change it, or + to add one."), __("Press Simulate to see what happens, then Switch on. Changing it later switches it off until you check it.")] },
		"sales-templates": { title: __("Message templates"), purpose: __("The wording of your emails, SMS and WhatsApp messages. Write it once, use it in many campaigns."),
			steps: [__("Start from a template or from blank."), __("Use fields such as the person’s first name; they are filled in for each person."), __("Approve a template before using it.")] },
		"sales-analytics": { title: __("Results"), purpose: __("How your campaigns are doing and which messages work best."),
			steps: [__("Pick a period."), __("Open a campaign to see who opened, clicked and replied.")] },
		"sales-channels": { title: __("Integrations"), purpose: __("Connect the places you talk to customers: email, SMS, WhatsApp, Facebook and more."),
			steps: [__("Open a tile and follow its steps."), __("A green tile means it is connected."), __("Your technical team can help with keys and web addresses.")] },
	};

	// Words used across the app, explained once.
	const WORDS = [
		[__("Lead"), __("A business or person you may want to sell to.")],
		[__("Fit"), __("How well a lead matches your ideal customer, 0 to 100.")],
		[__("Audience"), __("The group of people a campaign goes to.")],
		[__("Segment"), __("A saved group made by rules, always up to date. For example “opened an email in the last 30 days”.")],
		[__("Campaign"), __("A message, or a series of messages, sent to an audience.")],
		[__("Template"), __("Saved wording you can reuse. Fields such as the first name are filled in for each person.")],
		[__("Automation"), __("Steps that happen on their own for each person, such as a welcome email followed by a reminder.")],
		[__("Autopilot"), __("Lets the AI do routine work without asking each time. Sending to customers always keeps its safety checks.")],
		[__("Pilot"), __("A small test of a campaign on a few people before everyone.")],
		[__("Opt-out"), __("Someone who asked not to be contacted. They are never contacted again.")],
		[__("Double opt-in"), __("A new signup confirms their email first. Until then they get nothing.")],
		[__("Bounce"), __("An email that could not be delivered.")],
	];

	function open_guide(key) {
		const g = GUIDE[key];
		if (!g) return;
		const d = new frappe.ui.Dialog({ title: g.title, size: "large", fields: [{ fieldtype: "HTML", fieldname: "body" }] });
		d.fields_dict.body.$wrapper.html(`<div style="font-size:14px;line-height:1.5">
			<p>${e(g.purpose)}</p>
			<h5 style="margin-top:14px">${__("How to use this page")}</h5>
			<ol style="padding-left:20px">${g.steps.map((s) => `<li style="margin-bottom:4px">${e(s)}</li>`).join("")}</ol>
			<h5 style="margin-top:14px">${__("Words you will see")}</h5>
			<dl style="display:grid;grid-template-columns:130px 1fr;gap:4px 12px;margin:0">${WORDS.map(([w, t]) => `<dt style="font-weight:600">${e(w)}</dt><dd style="margin:0">${e(t)}</dd>`).join("")}</dl>
			<p class="text-muted" style="margin-top:14px;font-size:12px">${__("Nothing is sent to a customer without a person’s approval, unless a manager has switched autopilot on.")}</p></div>`);
		d.show();
		d.fields_dict.body.$wrapper.append(`<p style="margin-top:10px"><a href="#" class="rsa-replay">${__("Replay the welcome tour")}</a></p>`);
		d.fields_dict.body.$wrapper.find(".rsa-replay").on("click", (ev) => {
			ev.preventDefault();
			d.hide();
			if (window.rsa_run_tour) setTimeout(window.rsa_run_tour, 300);
		});
	}

	function attach() {
		try {
			const key = (frappe.get_route() || [])[0];
			const page = frappe.container && frappe.container.page && frappe.container.page.page;
			if (!GUIDE[key] || !page || page.__rsa_help === key || typeof page.add_inner_button !== "function") return;
			page.__rsa_help = key;
			page.add_inner_button(__("Help"), () => open_guide(key));
			try {  // once per browser: tell a new person the guide exists
				if (!localStorage.getItem("rsa_help_seen")) {
					localStorage.setItem("rsa_help_seen", "1");
					frappe.show_alert({ message: __("New here? Press Help on any page for a short guide."), indicator: "blue" }, 10);
				}
			} catch (err) { /* private window: no hint */ }
		} catch (err) { /* help is a convenience: never break a page for it */ }
	}

	frappe.router.on("change", () => { setTimeout(attach, 600); setTimeout(attach, 2500); });
	$(document).ready(() => setTimeout(attach, 1500));
})();
