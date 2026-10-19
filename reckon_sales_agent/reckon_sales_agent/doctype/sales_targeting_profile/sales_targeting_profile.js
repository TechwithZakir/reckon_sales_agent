frappe.ui.form.on("Sales Targeting Profile", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Suggest with AI"), () =>
			frappe
				.call({ method: "reckon_sales_agent.api.suggest_targeting", args: { profile: frm.doc.name }, freeze: true,
				        freeze_message: __("Asking Claude for search ideas...") })
				.then(() => frm.reload_doc())
		);
		if (frm.doc.ai_suggestions) {
			frm.add_custom_button(__("Apply AI Suggestions"), () =>
				frappe.confirm(__("Add the suggested keywords, segments, industries and exclusions to this profile?"), () =>
					frappe
						.call("reckon_sales_agent.api.apply_targeting_suggestions", { profile: frm.doc.name })
						.then(() => frm.reload_doc())
				)
			).addClass("btn-primary");
		}
		frm.add_custom_button(__("Preview Searches"), () =>
			frappe.call("reckon_sales_agent.api.preview_targeting", { profile: frm.doc.name }).then((r) => {
				const rows = (r.message || [])
					.map((q) => `<tr><td>${frappe.utils.escape_html(q.query_text)}</td><td>${q.max_results}</td></tr>`)
					.join("");
				frappe.msgprint({
					title: __("Planned searches"),
					message: rows
						? `<table class="table table-sm"><tr><th>${__("Search")}</th><th>${__("Max results")}</th></tr>${rows}</table>`
						: __("Add keywords, segments or industries first."),
					wide: true,
				});
			})
		);
		frm.add_custom_button(__("New Discovery Campaign"), () =>
			frappe.new_doc("Sales Discovery Campaign", { targeting_profile: frm.doc.name, campaign_name: frm.doc.profile_name })
		);
	},
});
