frappe.ui.form.on("Sales Social Post", {
	refresh(frm) {
		if (frm.is_new()) return;
		const call = (method, done, extra) =>
			frappe.call({ method: `reckon_sales_agent.api.${method}`, args: { post: frm.doc.name, ...(extra || {}) }, freeze: true })
				.then((r) => { frappe.show_alert({ message: done(r.message), indicator: "green" }); frm.reload_doc(); });
		const status = frm.doc.status;
		if (["Draft", "Pending Approval"].includes(status)) {
			frm.add_custom_button(__("Write with AI"), () =>
				call("write_social_post", (n) => __("{0} captions written; review them", [n])));
		}
		if (["Draft", "Failed"].includes(status)) {
			frm.add_custom_button(__("Submit for Approval"), () => call("submit_social_post", () => __("Submitted")));
		}
		if (status === "Pending Approval") {
			frm.add_custom_button(__("Approve"), () => {
				const issues = frm.doc.content_status === "Needs review";
				frappe.confirm(issues ? __("The content check found issues. Approve anyway? You confirm you have reviewed them.")
					: __("Approve this post for publishing?"), () =>
					call("approve_social_post", (s) => __(s === "Scheduled" ? "Approved and scheduled" : "Approved"),
						{ acknowledge_issues: issues ? 1 : 0 }));
			}).addClass("btn-primary");
		}
		if (["Approved", "Scheduled", "Partly Published", "Failed"].includes(status) && frm.doc.approved_by) {
			frm.add_custom_button(__("Publish Now"), () =>
				frappe.confirm(__("Publish to the selected accounts now?"), () => call("publish_social_post", (s) => __(s))));
		}
		if (frm.doc.content_status === "Needs review" && frm.doc.content_issues) {
			frm.dashboard.add_comment(`<b>${__("Content check")}:</b><br>${frappe.utils.escape_html(frm.doc.content_issues).replace(/\n/g, "<br>")}`, "orange", true);
		}
		frm.set_intro(__("Write with AI uses only your approved Knowledge Library. A person approves the exact text, image, accounts and time; any change needs approval again. Posts go out only through each platform's official API."), "blue");
	},
});
