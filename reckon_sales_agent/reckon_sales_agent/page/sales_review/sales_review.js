frappe.pages["sales-review"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Prospect Review"),
		single_column: true,
	});
	wrapper.review = new ProspectReview(page);
};

frappe.pages["sales-review"].on_page_show = function (wrapper) {
	wrapper.review && wrapper.review.load();
};

class ProspectReview {
	constructor(page) {
		this.page = page;
		this.status = page.add_field({
			fieldname: "status",
			label: __("Review Status"),
			fieldtype: "Select",
			options: "Pending\nDeferred\nApproved\nRejected",
			default: "Pending",
			change: () => this.load(),
		});
		this.qualification = page.add_field({
			fieldname: "qualification",
			label: __("Qualification"),
			fieldtype: "Select",
			options: "\nQualified\nNeeds Review\nNot Qualified",
			change: () => this.load(),
		});
		for (const [label, action] of [
			[__("Approve"), "approve"],
			[__("Defer"), "defer"],
			[__("Reject"), "reject"],
		]) {
			page.add_inner_button(label, () => this.review(action), __("Selected"));
		}
		page.add_inner_button(__("Research again"), () => this.research(), __("Selected"));
		this.$body = $('<div style="padding: 12px 0"></div>').appendTo(page.main);
	}

	selected() {
		return this.$body
			.find("input.review-select:checked")
			.map((_, el) => el.dataset.name)
			.get();
	}

	load() {
		frappe
			.call("reckon_sales_agent.api.review_queue", {
				status: this.status.get_value() || "Pending",
				qualification: this.qualification.get_value() || null,
			})
			.then((r) => this.render(r.message || []));
	}

	render(rows) {
		const e = frappe.utils.escape_html;
		const score = (v) => (v === null || v === undefined ? "–" : Math.round(v));
		const body = rows
			.map(
				(p) => `<tr>
				<td><input type="checkbox" class="review-select" data-name="${e(p.name)}"></td>
				<td><a href="/app/sales-prospect/${encodeURIComponent(p.name)}">${e(p.business_name)}</a>
					${p.possible_duplicate_of ? `<div class="small text-warning">${__("Possible duplicate of")} ${e(p.possible_duplicate_of)}</div>` : ""}
					<div class="small text-muted">${e(p.industry || "")} · ${e(p.city || "")}</div></td>
				<td>${/^https?:\/\//i.test(p.website || "") ? `<a href="${e(p.website)}" target="_blank" rel="noopener noreferrer">${e(p.website)}</a>` : e(p.website || "–")}</td>
				<td>${e(__(p.qualification_status || "Not scored"))}</td>
				<td><b>${p.deal_probability ? score(p.deal_probability) + "%" : "–"}</b></td>
				<td>${score(p.fit_score)}${p.ai_fit_score ? ` <span class="text-muted small">(AI ${score(p.ai_fit_score)})</span>` : ""}</td>
				<td>${score(p.buying_signal_score)}</td>
				<td>${score(p.evidence_confidence)}</td>
				<td>${e(__(p.contactability || ""))}</td>
				<td>${p.latest_research ? `<a href="/app/sales-research-report/${encodeURIComponent(p.latest_research)}">${__("Evidence")}</a>` : e(__(p.research_status || ""))}</td>
			</tr>`
			)
			.join("");
		this.$body.html(`
			<table class="table table-hover">
				<thead><tr>
					<th><input type="checkbox" class="review-all"></th>
					<th>${__("Business")}</th><th>${__("Website")}</th><th>${__("Result")}</th>
					<th>${__("Deal probability")}</th><th>${__("Fit")}</th><th>${__("Buying signal")}</th><th>${__("Evidence")}</th>
					<th>${__("Contact")}</th><th>${__("Research")}</th>
				</tr></thead>
				<tbody>${body || `<tr><td colspan="10" class="text-muted">${__("Nothing to review")}</td></tr>`}</tbody>
			</table>`);
		this.$body.find(".review-all").on("change", (ev) =>
			this.$body.find(".review-select").prop("checked", ev.target.checked)
		);
	}

	review(action) {
		const prospects = this.selected();
		if (!prospects.length) return frappe.msgprint(__("Select prospects first."));
		frappe
			.call("reckon_sales_agent.api.review_prospects", { prospects, action })
			.then(() => {
				frappe.show_alert({ message: __("{0} prospects updated", [prospects.length]), indicator: "green" });
				this.load();
			});
	}

	research() {
		const prospects = this.selected();
		if (!prospects.length) return frappe.msgprint(__("Select prospects first."));
		frappe.call("reckon_sales_agent.api.research", { prospects }).then(() => {
			frappe.show_alert({ message: __("Research queued"), indicator: "blue" });
			this.load();
		});
	}
}
