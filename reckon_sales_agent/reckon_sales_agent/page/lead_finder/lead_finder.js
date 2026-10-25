// Lead Finder Studio: source -> targeting -> campaign & schedule -> launch with live progress.
// Wrapped in a closure: Desk evaluates page scripts in the global scope.
(() => {
	frappe.pages["lead-finder"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Lead Finder Studio"), single_column: true });
		page.add_inner_button(__("Prospect Review"), () => frappe.set_route("sales-review"));
		page.add_inner_button(__("Campaign Analytics"), () => frappe.set_route("sales-analytics"));
		wrapper.studio = new LeadFinderStudio(page);
	};

	frappe.pages["lead-finder"].on_page_show = function (wrapper) {
		wrapper.studio && wrapper.studio.load();
	};

	frappe.pages["lead-finder"].on_page_hide = function (wrapper) {
		wrapper.studio && wrapper.studio.stop_polling();
	};

	const LFS_API = "reckon_sales_agent.api_studio.";
	const LFS_ICONS = {
		map: '<path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2z"/><path d="M9 4v14M15 6v14"/>',
		pin: '<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>',
		browser: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M7 6.5h.01M10 6.5h.01"/>',
		globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 2.5 15.3 0 18M12 3c-2.5 2.7-2.5 15.3 0 18"/>',
		file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
		spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 17l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z"/>',
		check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
	};
	const BD_CITIES = ["Dhaka", "Chattogram", "Gazipur", "Narayanganj", "Sylhet", "Khulna", "Rajshahi", "Barishal",
		"Rangpur", "Mymensingh", "Cumilla", "Bogura", "Cox's Bazar", "Jashore"];

	function lfs_icon(name, size = 20) {
		return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
			stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${LFS_ICONS[name] || LFS_ICONS.spark}</svg>`;
	}
	const e = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const lines = (v) => (v || "").split("\n").map((s) => s.trim()).filter(Boolean);

	class LeadFinderStudio {
		constructor(page) {
			this.page = page;
			this.$root = $('<div class="lfs"></div>').appendTo(page.main);
			this.step = 1;
			this.state = { connector: null, connectorType: null, profile: null, chips: {}, locations: [], job: null };
			this.timer = null;
		}

		call(method, args) {
			return frappe.xcall(LFS_API + method, args || {});
		}

		load() {
			return this.call("bootstrap").then((data) => {
				this.data = data;
				this.render();
			});
		}

		stop_polling() {
			clearTimeout(this.timer);
			this.timer = null;
		}

		// ---------------------------------------------------------------- layout
		render() {
			const w = this.data.workers || {};
			const worker = !w.known
				? `<span class="lfs-pill"><span class="dot"></span>${__("Worker status unknown")}</span>`
				: w.long
					? `<span class="lfs-pill ok"><span class="dot"></span>${__("Background worker online")}</span>`
					: `<span class="lfs-pill bad"><span class="dot"></span>${__("No background worker for jobs")}</span>`;
			const usage = this.data.usage || {};
			const disc = usage["Discovery Result"] || { used: 0, limit: 0 };
			this.$root.html(`
				<div class="lfs-hero">
					<div>
						<h2>${__("Find your next customers")}</h2>
						<p>${__("Pick a source, describe who you sell to, and let the agent find, research and score leads for you.")}</p>
					</div>
					<div class="lfs-pills">
						${worker}
						<span class="lfs-pill"><span class="dot"></span>${__("{0} of {1} leads this month", [disc.used, disc.limit])}</span>
						${this.data.ai_available ? `<span class="lfs-pill ok"><span class="dot"></span>${__("AI assist on")}</span>` : ""}
					</div>
				</div>
				<div class="lfs-steps">${[__("Source"), __("Who to find"), __("Campaign & schedule"), __("Launch")]
					.map((label, i) => `<div class="lfs-step ${i + 1 === this.step ? "active" : i + 1 < this.step ? "done" : ""}" data-step="${i + 1}">
						<span class="num">${i + 1 < this.step ? lfs_icon("check", 14) : i + 1}</span><span class="label">${e(label)}</span></div>`)
					.join("")}</div>
				<div class="lfs-body"></div>
				<div class="lfs-recent"></div>`);
			this.$root.find(".lfs-step.done").on("click", (ev) => this.go(Number(ev.currentTarget.dataset.step)));
			const body = this.$root.find(".lfs-body");
			[null, this.render_source, this.render_targeting, this.render_campaign, this.render_launch][this.step].call(this, body);
			this.render_recent(this.$root.find(".lfs-recent"));
		}

		go(step) {
			if (step !== 4) this.stop_polling();
			this.step = step;
			this.render();
			window.scrollTo({ top: 0, behavior: "smooth" });
		}

		actions(body, { back, next, nextLabel, nextIcon }) {
			const $a = $(`<div class="lfs-actions">
				${back ? `<button class="btn btn-default btn-sm lfs-back">${__("Back")}</button>` : "<span></span>"}
				<div class="right">${next ? `<button class="btn btn-primary btn-sm lfs-next">${nextIcon ? lfs_icon(nextIcon, 14) + " " : ""}${e(nextLabel || __("Continue"))}</button>` : ""}</div>
			</div>`).appendTo(body);
			$a.find(".lfs-back").on("click", back);
			$a.find(".lfs-next").on("click", next);
			return $a;
		}

		// ---------------------------------------------------------------- 1. source
		render_source(body) {
			const panel = $(`<div class="lfs-panel"><h3>${__("Where should the agent look?")}</h3>
				<p class="lead">${__("Choose a lead source. Sources marked Ready are set up for your company.")}</p></div>`).appendTo(body);
			const groups = {};
			this.data.catalog.forEach((c) => (groups[c.group] = groups[c.group] || []).push(c));
			Object.entries(groups).forEach(([group, items]) => {
				panel.append(`<div class="lfs-group-title">${e(group)}</div>`);
				const grid = $('<div class="lfs-cards"></div>').appendTo(panel);
				items.forEach((c) => {
					const badge = !c.available ? `<span class="lfs-badge off">${__("Not enabled")}</span>`
						: c.ready ? `<span class="lfs-badge ready">${__("Ready")}</span>`
							: c.experimental ? `<span class="lfs-badge exp">${__("Experimental")}</span>` : "";
					const card = $(`<button type="button" class="lfs-card ${c.available ? "" : "disabled"} ${this.state.connectorType === c.type ? "selected" : ""}"
						title="${e(c.available ? c.subtitle : c.reason)}">
						${badge}<div class="icon">${lfs_icon(c.icon)}</div>
						<div class="title">${e(c.title)}</div><div class="sub">${e(c.available ? c.subtitle : c.reason)}</div></button>`).appendTo(grid);
					card.on("click", () => c.available && this.pick_source(c));
				});
			});
			const setup = $('<div class="lfs-setup"></div>').appendTo(panel);
			if (this.state.connectorType) this.render_source_setup(setup);
			this.actions(body, { next: () => this.go(2), nextLabel: __("Continue") }).find(".lfs-next").prop("disabled", !this.state.connector);
		}

		pick_source(c) {
			this.state.connectorType = c.type;
			this.state.connector = c.ready ? c.connector : null;
			this.render();
		}

		render_source_setup(el) {
			const c = this.data.catalog.find((x) => x.type === this.state.connectorType);
			if (c.ready) {
				el.html(`<div class="lfs-note">${lfs_icon("check", 14)} ${__("{0} is ready to use.", [e(c.title)])}</div>`);
				return;
			}
			if (!this.data.can_manage) {
				el.html(`<div class="lfs-note warn">${__("Ask a Sales Agent admin or manager to set up this source.")}</div>`);
				return;
			}
			const ownData = ["fixture", "manual_import"].includes(c.type);
			el.html(`<div class="lfs-panel" style="margin-top:14px">
				<h3>${__("Set up {0}", [e(c.title)])}</h3>
				${c.needs_urls ? `<div class="lfs-field" style="margin:10px 0"><label>${__("Directory start URLs (one per line)")}</label>
					<textarea class="form-control lfs-urls" rows="3" placeholder="https://directory.example/members?q={keyword}&city={location}"></textarea>
					<div class="hint">${__("{keyword} and {location} are filled in for each search.")}</div></div>` : ""}
				${ownData ? "" : `<label class="lfs-toggle" style="margin:10px 0"><input type="checkbox" class="lfs-policy">
					<span><span class="t">${__("I confirm we may use this source")}</span><br>
					<span class="d">${__("Data is kept per your provider's retention rules and the source's terms.")}</span></span></label>`}
				<button class="btn btn-primary btn-sm lfs-enable">${__("Enable source")}</button>
				<div class="lfs-setup-result"></div></div>`);
			el.find(".lfs-enable").on("click", () => {
				if (!ownData && !el.find(".lfs-policy").is(":checked")) {
					frappe.msgprint(__("Please confirm you may use this source."));
					return;
				}
				this.call("setup_connector", {
					connector_type: c.type, confirm_policy: 1,
					start_urls: c.needs_urls ? el.find(".lfs-urls").val() : null,
				}).then((r) => {
					if (r.status === "ready") {
						frappe.show_alert({ message: __("Source ready"), indicator: "green" });
						this.state.connector = r.connector;
						this.load();
					} else {
						el.find(".lfs-setup-result").html(`<div class="lfs-note bad">${e(r.error || __("Not ready"))}</div>`);
					}
				});
			});
		}

		// ---------------------------------------------------------------- 2. targeting
		render_targeting(body) {
			const profiles = this.data.profiles || [];
			const p = profiles.find((x) => x.name === this.state.profile) || {};
			// Typed values live in state so any re-render (AI suggestions, loading locations) keeps them.
			const form = (this.state.form = this.state.form || {});
			if (form.pname == null) form.pname = p.profile_name || "";
			if (form.market == null) form.market = p.market || "B2B";
			const panel = $(`<div class="lfs-panel"><h3>${__("Who should the agent find?")}</h3>
				<p class="lead">${__("Type a word and press Enter to add it. Use English or Bangla.")}</p>
				<div class="lfs-grid2">
					<div class="lfs-field"><label>${__("Saved profile")}</label>
						<select class="form-control lfs-profile"><option value="">${__("New profile")}</option>
						${profiles.map((x) => `<option value="${e(x.name)}" ${x.name === this.state.profile ? "selected" : ""}>${e(x.profile_name)}</option>`).join("")}</select></div>
					<div class="lfs-field"><label>${__("Profile name")}</label>
						<input class="form-control lfs-pname" value="${e(form.pname)}" placeholder="${__("e.g. Pharmacies in Dhaka")}"></div>
					<div class="lfs-field"><label>${__("Market")}</label><div class="lfs-seg lfs-market">
						${["B2B", "B2B2C", "B2G"].map((m) => `<button type="button" data-v="${m}" class="${form.market === m ? "on" : ""}">${m}</button>`).join("")}</div></div>
					<div></div>
					${this.chip_field("keywords", __("Search keywords"), __("e.g. pharmacy, medicine shop, ফার্মেসি"), p.keywords)}
					${this.chip_field("b2b_segments", __("Buyer types (B2B segments)"), __("e.g. distributors, wholesalers"), p.b2b_segments)}
					${this.chip_field("industries", __("Industries"), __("e.g. Pharmaceutical"), p.industries)}
					${this.chip_field("interests", __("Needs your offer solves"), __("e.g. route planning, credit control"), p.interests)}
					${this.chip_field("locations", __("Locations"), __("Type Area, City and press Enter"), null)}
					${this.chip_field("exclude_keywords", __("Exclude businesses mentioning"), __("e.g. hospital"), p.exclude_keywords)}
				</div>
				<datalist id="lfs-cities">${BD_CITIES.map((c) => `<option value="${e(c)}">`).join("")}</datalist>
				<div class="lfs-ai"></div></div>`).appendTo(body);
			this.bind_chips(panel);
			if (this.state.profile && !this.state.locations_loaded) {
				this.call("profile_locations", { profile: this.state.profile }).then((rows) => {
					this.state.locations_loaded = true;
					this.state.chips.locations = rows.map((r) => [r.area, r.city].filter(Boolean).join(", "));
					this.render();
				});
			}
			panel.find(".lfs-profile").on("change", (ev) => {
				this.state.profile = ev.target.value || null;
				this.state.chips = {};
				this.state.form = null;
				this.state.locations_loaded = false;
				this.render();
			});
			panel.find(".lfs-pname").on("input", (ev) => (form.pname = ev.target.value));
			panel.find(".lfs-market button").on("click", (ev) => {
				form.market = ev.currentTarget.dataset.v;
				panel.find(".lfs-market button").removeClass("on");
				$(ev.currentTarget).addClass("on");
			});
			if (this.data.ai_available) {
				const ai = panel.find(".lfs-ai").html(`<div class="lfs-note">${lfs_icon("spark", 14)}
					${__("Let AI suggest more keywords, Bangla variants and buyer types.")}
					<button class="btn btn-xs btn-default lfs-suggest" style="margin-left:8px">${__("Suggest with AI")}</button></div>`);
				ai.find(".lfs-suggest").on("click", () => this.save_profile(panel).then((name) =>
					frappe.xcall("reckon_sales_agent.api.suggest_targeting", { profile: name }).then((s) => {
						if (!s) return;
						["keywords", "b2b_segments", "industries", "exclude_keywords"].forEach((k) => {
							const extra = k === "keywords" ? [...(s.keywords || []), ...(s.bangla_keywords || [])] : s[k] || [];
							this.state.chips[k] = [...new Set([...(this.state.chips[k] || []), ...extra])];
						});
						frappe.show_alert({ message: __("AI suggestions added; remove any you don't want."), indicator: "blue" });
						this.render();
					})));
			}
			this.actions(body, {
				back: () => this.go(1),
				next: () => this.save_profile(panel).then(() => this.go(3)),
				nextLabel: __("Save & continue"),
			});
		}

		chip_field(key, label, placeholder, stored) {
			if (!this.state.chips[key]) this.state.chips[key] = key === "locations" ? [] : lines(stored);
			return `<div class="lfs-field"><label>${e(label)}</label>
				<div class="lfs-chips" data-chip="${key}" data-placeholder="${e(placeholder)}"></div></div>`;
		}

		bind_chips(panel) {
			panel.find(".lfs-chips").each((_, box) => this.draw_chips($(box)));
		}

		// Redraws one chip box only, so other typed fields on the page are untouched.
		draw_chips($box, focus = false) {
			const key = $box.data("chip");
			const list = this.state.chips[key] || (this.state.chips[key] = []);
			$box.html(list.map((v, i) =>
				`<span class="lfs-chip">${e(v)}<button type="button" data-i="${i}" aria-label="${__("Remove")}">×</button></span>`).join("")
				+ `<input placeholder="${e($box.data("placeholder"))}" ${key === "locations" ? 'list="lfs-cities"' : ""}>`);
			const add = (raw) => {
				raw.split(key === "locations" ? /;/ : /[,;]/).map((s) => s.trim()).filter(Boolean).forEach((v) => {
					if (!list.some((x) => x.toLowerCase() === v.toLowerCase())) list.push(v);
				});
				this.draw_chips($box, true);
			};
			const $input = $box.find("input");
			$input.on("keydown", (ev) => {
				if ((ev.key === "Enter" || (ev.key === "," && key !== "locations")) && ev.target.value.trim()) {
					ev.preventDefault();
					add(ev.target.value);
				} else if (ev.key === "Backspace" && !ev.target.value && list.length) {
					list.pop();
					this.draw_chips($box, true);
				}
			}).on("blur", (ev) => ev.target.value.trim() && add(ev.target.value));
			$box.find(".lfs-chip button").on("click", (ev) => {
				list.splice(Number(ev.currentTarget.dataset.i), 1);
				this.draw_chips($box, true);
			});
			$box.off("click.lfs").on("click.lfs", (ev) => ev.target === $box[0] && $input.trigger("focus"));
			if (focus) $input.trigger("focus");
		}

		save_profile(panel) {
			const data = {
				name: this.state.profile,
				profile_name: (this.state.form || {}).pname || panel.find(".lfs-pname").val(),
				market: (this.state.form || {}).market || "B2B",
				locations: (this.state.chips.locations || []).map((label) => {
					const parts = label.split(",").map((s) => s.trim()).filter(Boolean);
					return parts.length > 1 ? { area: parts.slice(0, -1).join(", "), city: parts[parts.length - 1] } : { city: parts[0] };
				}),
			};
			["keywords", "b2b_segments", "industries", "interests", "exclude_keywords"].forEach((k) => (data[k] = (this.state.chips[k] || []).join("\n")));
			return this.call("save_targeting", { data: JSON.stringify(data) }).then((name) => {
				this.state.profile = name;
				return this.call("bootstrap").then((d) => ((this.data = d), name));
			});
		}

		// ---------------------------------------------------------------- 3. campaign & schedule
		render_campaign(body) {
			const s = (this.state.campaign = this.state.campaign || {
				campaign_name: (this.data.profiles.find((p) => p.name === this.state.profile) || {}).profile_name || "",
				target_count: Math.min(50, this.data.max_results_per_job), per_query_limit: 20,
				auto_research: true, use_ai_planner: false, mode: "now", schedule: "Weekly", run_at_time: "09:00",
			});
			const panel = $(`<div class="lfs-panel"><h3>${__("How many leads, and when?")}</h3>
				<p class="lead">${__("Run once now, keep it running on a schedule, or both.")}</p>
				<div class="lfs-grid2">
					<div class="lfs-field"><label>${__("Campaign name")}</label><input class="form-control lfs-cname" value="${e(s.campaign_name)}"></div>
					<div class="lfs-field"><label>${__("Leads to find per run")}: <b class="lfs-count-v">${s.target_count}</b></label>
						<input type="range" class="lfs-count" min="5" max="${this.data.max_results_per_job}" step="5" value="${s.target_count}" style="width:100%">
						<div class="hint">${__("Your plan allows up to {0} per run.", [this.data.max_results_per_job])}</div></div>
					<div class="lfs-field"><label>${__("When")}</label><div class="lfs-seg lfs-mode">
						${[["now", __("Run now")], ["both", __("Now + repeat")], ["schedule", __("Schedule only")]]
							.map(([v, l]) => `<button type="button" data-v="${v}" class="${s.mode === v ? "on" : ""}">${e(l)}</button>`).join("")}</div></div>
					<div class="lfs-field lfs-sched" style="${s.mode === "now" ? "display:none" : ""}"><label>${__("Repeat")}</label>
						<div style="display:flex; gap:8px"><select class="form-control lfs-freq">
							${["Daily", "Weekly", "Monthly"].map((f) => `<option value="${f}" ${s.schedule === f ? "selected" : ""}>${__(f)}</option>`).join("")}</select>
						<input type="time" class="form-control lfs-time" value="${e(s.run_at_time)}"></div>
						<div class="hint">${__("Runs in the background at this time (server time).")}</div></div>
					<label class="lfs-toggle"><input type="checkbox" class="lfs-research" ${s.auto_research ? "checked" : ""}>
						<span><span class="t">${__("Research websites automatically")}</span><br><span class="d">${__("Find emails, social profiles and buying signals, then score each lead.")}</span></span></label>
					<label class="lfs-toggle" style="${this.data.ai_available ? "" : "opacity:.5"}"><input type="checkbox" class="lfs-aiplan" ${s.use_ai_planner ? "checked" : ""} ${this.data.ai_available ? "" : "disabled"}>
						<span><span class="t">${__("Widen searches with AI")}</span><br><span class="d">${__("Adds related keywords and Bangla variants each run.")}</span></span></label>
				</div>
				<div class="lfs-preview"></div></div>`).appendTo(body);
			const sync = () => Object.assign(s, {
				campaign_name: panel.find(".lfs-cname").val(), target_count: Number(panel.find(".lfs-count").val()),
				auto_research: panel.find(".lfs-research").is(":checked"), use_ai_planner: panel.find(".lfs-aiplan").is(":checked"),
				schedule: panel.find(".lfs-freq").val(), run_at_time: panel.find(".lfs-time").val(),
			});
			panel.find(".lfs-count").on("input", (ev) => panel.find(".lfs-count-v").text(ev.target.value));
			panel.find(".lfs-mode button").on("click", (ev) => {
				sync();
				s.mode = ev.currentTarget.dataset.v;
				panel.find(".lfs-mode button").removeClass("on");
				$(ev.currentTarget).addClass("on");
				panel.find(".lfs-sched").toggle(s.mode !== "now");
			});
			const $a = this.actions(body, { back: () => (sync(), this.go(2)), next: () => (sync(), this.go(4)), nextLabel: __("Review & launch") });
			$('<button class="btn btn-default btn-sm">' + __("Preview searches") + "</button>").prependTo($a.find(".right")).on("click", () => {
				sync();
				frappe.xcall("reckon_sales_agent.api.preview_targeting",
					{ profile: this.state.profile, target_count: s.target_count, per_query_limit: s.per_query_limit }).then((rows) => {
					panel.find(".lfs-preview").html(rows.length
						? `<div class="lfs-group-title">${__("Searches to run: {0}", [rows.length])}</div><div class="lfs-list">${rows.map((r) =>
							`<div class="lfs-row"><div class="main"><div>${e(r.query_text)}</div></div><span class="meta">${__("up to {0}", [r.max_results])}</span></div>`).join("")}</div>`
						: `<div class="lfs-note warn">${__("Add keywords or segments in the previous step.")}</div>`);
				});
			});
		}

		// ---------------------------------------------------------------- 4. launch & progress
		render_launch(body) {
			if (this.state.job) return this.render_progress(body);
			const s = this.state.campaign;
			const src = this.data.catalog.find((c) => c.connector === this.state.connector) || {};
			const prof = this.data.profiles.find((p) => p.name === this.state.profile) || {};
			const when = s.mode === "now" ? __("Once, right now")
				: s.mode === "both" ? __("Now, then {0} at {1}", [__(s.schedule), s.run_at_time]) : __("{0} at {1}", [__(s.schedule), s.run_at_time]);
			$(`<div class="lfs-panel"><h3>${__("Ready to launch")}</h3><p class="lead">${__("Check the summary, then start.")}</p>
				<div class="lfs-list">
					${[[__("Source"), src.title], [__("Targeting"), prof.profile_name], [__("Campaign"), s.campaign_name || __("Lead discovery")],
						[__("Leads per run"), s.target_count], [__("When"), when],
						[__("Research"), s.auto_research ? __("On") : __("Off")]].map(([k, v]) =>
						`<div class="lfs-row"><span class="meta">${e(k)}</span><div class="main"><div><b>${e(v)}</b></div></div></div>`).join("")}
				</div></div>`).appendTo(body);
			this.actions(body, {
				back: () => this.go(3), nextIcon: "spark",
				nextLabel: s.mode === "schedule" ? __("Save schedule") : __("Start discovery"),
				next: (ev) => {
					$(ev.currentTarget).prop("disabled", true);
					this.call("launch", { data: JSON.stringify({ ...s, name: this.state.campaign_name_saved, connector: this.state.connector, targeting_profile: this.state.profile }) })
						.then((r) => {
							this.state.campaign_name_saved = r.campaign;
							if (r.job) {
								this.state.job = r.job;
								this.render();
							} else {
								frappe.msgprint({ title: __("Scheduled"), indicator: "green",
									message: __("The agent will run this campaign on {0} at {1}, then repeat.", [e(r.next_run_on), e(r.run_at_time || "")]) });
								this.reset();
							}
						})
						.catch(() => $(ev.currentTarget).prop("disabled", false));
				},
			});
		}

		render_progress(body) {
			const panel = $(`<div class="lfs-panel"><div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
				<h3>${__("Discovery in progress")}</h3><span class="lfs-state Queued lfs-status">${__("Queued")}</span></div>
				<div class="lfs-progress indeterminate" style="margin-top:12px"><div></div></div>
				<div class="lfs-stats">
					<div class="lfs-stat"><div class="v lfs-s-search">0/0</div><div class="k">${__("Searches done")}</div></div>
					<div class="lfs-stat"><div class="v lfs-s-new">0</div><div class="k">${__("New leads")}</div></div>
					<div class="lfs-stat"><div class="v lfs-s-dup">0</div><div class="k">${__("Duplicates skipped")}</div></div>
					<div class="lfs-stat"><div class="v lfs-s-res">0</div><div class="k">${__("Researched")}</div></div>
				</div><div class="lfs-alert"></div>
				<div class="lfs-two"><div><div class="lfs-group-title">${__("Searches")}</div><div class="lfs-list lfs-searches"></div></div>
					<div><div class="lfs-group-title">${__("Newest leads")}</div><div class="lfs-list lfs-leads"></div></div></div>
			</div>`).appendTo(body);
			const $a = this.actions(body, { back: null, next: () => frappe.set_route("sales-review"), nextLabel: __("Review leads") });
			$(`<button class="btn btn-default btn-sm">${__("New search")}</button>`).prependTo($a.find(".right")).on("click", () => this.reset());
			$(`<button class="btn btn-default btn-sm">${__("Open job")}</button>`).prependTo($a.find(".right"))
				.on("click", () => frappe.set_route("Form", "Sales Discovery Job", this.state.job));
			this.poll(panel);
		}

		poll(panel) {
			this.stop_polling();
			this.call("progress", { job: this.state.job }).then((r) => {
				const j = r.job;
				const total = j.progress_total || 0;
				const pct = total ? Math.round((100 * (j.progress_done || 0)) / total) : 0;
				const running = ["Queued", "Running"].includes(j.status);
				panel.find(".lfs-status").attr("class", `lfs-state ${e(j.status)} lfs-status`).text(__(j.status));
				panel.find(".lfs-progress").toggleClass("indeterminate", j.status === "Queued").find("div").css("width", j.status === "Queued" ? "" : `${j.status === "Completed" ? 100 : pct}%`);
				panel.find(".lfs-s-search").text(`${j.progress_done || 0}/${total}`);
				panel.find(".lfs-s-new").text(j.created_count || 0);
				panel.find(".lfs-s-dup").text(j.duplicate_count || 0);
				panel.find(".lfs-s-res").text(r.researched || 0);
				let alert = "";
				if (j.status === "Queued" && r.workers && r.workers.known && !r.workers.long) {
					alert = `<div class="lfs-note bad">${__("No background worker is processing jobs, so this job is waiting. Ask your administrator to start the bench workers (bench doctor / supervisorctl).")}</div>`;
				} else if (j.status === "Failed") {
					alert = `<div class="lfs-note bad"><b>${e(j.error_code || __("Failed"))}</b>: ${e(j.error_detail || "")}</div>`;
				} else if (j.status === "Completed") {
					alert = `<div class="lfs-note">${lfs_icon("check", 14)} ${__("Done. Research and scoring continue in the background; leads appear in Prospect Review.")}</div>`;
				}
				panel.find(".lfs-alert").html(alert);
				panel.find(".lfs-searches").html(r.searches.map((q) => `<div class="lfs-row"><div class="main"><div>${e(q.query_text)}</div>
					<div class="meta">${q.results != null && q.status === "Done" ? __("{0} results", [q.results]) : ""}</div></div>
					<span class="lfs-state ${e(q.status)}">${e(__(q.status))}</span></div>`).join("") || `<div class="lfs-row meta">${__("Planning…")}</div>`);
				panel.find(".lfs-leads").html(r.prospects.map((p) => `<div class="lfs-row"><div class="main">
					<div><a href="/desk/sales-prospect/${encodeURIComponent(p.name)}">${e(p.business_name)}</a></div>
					<div class="meta">${e([p.city, p.phone].filter(Boolean).join(" · "))}</div></div>
					<span class="meta">${p.deal_probability ? e(Math.round(p.deal_probability)) + "%" : e(__(p.research_status || "New"))}</span></div>`).join("")
					|| `<div class="lfs-row meta">${__("Leads will appear here as they are found.")}</div>`);
				if (running || r.prospects.some((p) => p.research_status === "Queued")) {
					this.timer = setTimeout(() => this.poll(panel), 3000);
				}
			});
		}

		reset() {
			this.stop_polling();
			this.state = { connector: this.state.connector, connectorType: this.state.connectorType, profile: this.state.profile, chips: {}, job: null };
			this.load().then(() => this.go(1));
		}

		// ---------------------------------------------------------------- recent campaigns
		render_recent(el) {
			const rows = this.data.campaigns || [];
			if (!rows.length) return;
			el.html(`<div class="lfs-group-title">${__("Your discovery campaigns")}</div><div class="lfs-list">${rows.map((c) => `
				<div class="lfs-row"><div class="main"><div><a href="/desk/sales-discovery-campaign/${encodeURIComponent(c.name)}">${e(c.campaign_name)}</a></div>
				<div class="meta">${c.schedule ? e(__("{0} at {1} · next {2}", [__(c.schedule), (c.run_at_time || "").slice(0, 5) || "—", c.next_run_on || "—"])) : e(__("Manual"))}
				· ${e(__("{0} leads", [c.prospects_found || 0]))}</div></div>
				<div style="display:flex;gap:6px;align-items:center"><span class="lfs-state ${e(c.status)}">${e(__(c.status))}</span>
				${c.last_job ? `<button class="btn btn-xs btn-default lfs-watch" data-job="${e(c.last_job)}">${__("Progress")}</button>` : ""}</div></div>`).join("")}</div>`);
			el.find(".lfs-watch").on("click", (ev) => {
				this.state.job = ev.currentTarget.dataset.job;
				this.step = 4;
				this.render();
			});
		}
	}
})();
