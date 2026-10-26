frappe.ui.form.on("Sales Social Account", {
	refresh(frm) {
		frm.set_intro(__("Connect a Facebook Page (Page ID + long-lived Page access token), an Instagram professional account linked to a Page (IG user ID + the Page token), or a LinkedIn organization page (organization ID + admin token with w_organization_social). The token is stored encrypted."), "blue");
		if (frm.is_new()) return;
		frm.add_custom_button(__("Check Connection"), () =>
			frappe.call({ method: "reckon_sales_agent.api.check_social_account", args: { account: frm.doc.name }, freeze: true })
				.then((r) => { frappe.show_alert({ message: __("Connected: {0}", [r.message]), indicator: "green" }); frm.reload_doc(); }));
	},
});
