// Automation Studio: a list of automations and a visual flow editor (our own canvas, no flow library).
// Wrapped in a closure: Desk evaluates page scripts in the global scope.
(() => {
	frappe.pages["automation-studio"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Automation Studio"), single_column: true });
		page.add_inner_button(__("Campaign Studio"), () => frappe.set_route("campaign-studio"));
		page.add_inner_button(__("Capture Studio"), () => frappe.set_route("capture-studio"));
		wrapper.aut = new Studio(page);
	};
	frappe.pages["automation-studio"].on_page_show = (wrapper) => wrapper.aut && wrapper.aut.show();

	const API = "reckon_sales_agent.api_automation.";
	const e = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const num = (v) => Number(v || 0).toLocaleString();
	const MANAGER_ROLES = ["Reckon Sales Agent Admin", "Reckon Sales Agent Manager", "Reckon Vendor Superuser", "System Manager"];
	// The server decides who may change anything; this only hides buttons that would be refused.
	const can_manage = () => frappe.session.user === "Administrator" || MANAGER_ROLES.some((role) => frappe.user.has_role(role));
	const W = 232, H = 62, GX = 34, GY = 62, PAD = 40;
	const KINDS = {
		trigger: { label: __("Trigger"), color: "var(--c-trigger)" }, send: { label: __("Send"), color: "var(--c-send)" },
		wait: { label: __("Wait"), color: "var(--c-wait)" }, condition: { label: __("Condition"), color: "var(--c-condition)" },
		action: { label: __("Action"), color: "var(--c-action)" }, webhook: { label: __("Webhook"), color: "var(--c-webhook)" },
	};
	const PICK = [["send", __("Message"), __("Send an approved template"), __("Email, SMS or WhatsApp to everyone who reaches this step.")],
		["wait", __("Timing"), __("Wait"), __("Pause for minutes, hours or days before moving on.")],
		["condition", __("Logic"), __("Condition"), __("Split into Yes and No: opened, clicked, replied, has a tag, is in a segment.")],
		["action", __("Contact"), __("Action"), __("Add or remove a tag, create a CRM task, notify the owner, change a field, or stop.")],
		["webhook", __("Integration"), __("Webhook"), __("Send the person's details to another system's web address.")]];
	const DEFAULTS = {
		send: () => ({ template: "" }), wait: () => ({ amount: 1, unit: "days" }),
		condition: () => ({ check: "opened", ref: "any", wait_days: 3, tag: "", segment: "" }), action: () => ({ do: "add_tag", value: "" }), webhook: () => ({ url: "" }),
	};
	const uid = () => "n" + Math.random().toString(36).slice(2, 8);
	const store = {
		get(key, fallback) { try { return localStorage.getItem(key) || fallback; } catch (err) { return fallback; } },
		set(key, value) { try { localStorage.setItem(key, value); } catch (err) { /* private window */ } },
	};
	const STARTERS = {
		welcome: { label: __("Welcome series"), event: "signup", build: () => ({ start: "n1", nodes: {
			n1: { type: "trigger", config: { event: "signup" }, next: "n2" }, n2: { type: "send", config: { template: "" }, next: "n3" },
			n3: { type: "wait", config: { amount: 2, unit: "days" }, next: "n4" },
			n4: { type: "condition", config: { check: "opened", ref: "n2", wait_days: 3 }, yes: "n5", no: "n6" },
			n5: { type: "action", config: { do: "add_tag", value: "engaged" }, next: null }, n6: { type: "send", config: { template: "" }, next: null } } }) },
		reengage: { label: __("Re-engage quiet readers"), event: "segment_joined", build: () => ({ start: "n1", nodes: {
			n1: { type: "trigger", config: { event: "segment_joined" }, next: "n2" }, n2: { type: "send", config: { template: "" }, next: "n3" },
			n3: { type: "wait", config: { amount: 3, unit: "days" }, next: "n4" },
			n4: { type: "condition", config: { check: "clicked", ref: "n2", wait_days: 2 }, yes: "n5", no: "n6" },
			n5: { type: "action", config: { do: "create_task", value: "Call: clicked the re-engagement email" }, next: null },
			n6: { type: "action", config: { do: "add_tag", value: "cold" }, next: null } } }) },
		handoff: { label: __("Nurture, then hand to sales"), event: "signup", build: () => ({ start: "n1", nodes: {
			n1: { type: "trigger", config: { event: "signup" }, next: "n2" }, n2: { type: "send", config: { template: "" }, next: "n3" },
			n3: { type: "wait", config: { amount: 1, unit: "days" }, next: "n4" },
			n4: { type: "condition", config: { check: "replied", ref: "n2", wait_days: 2 }, yes: "n5", no: "n6" },
			n5: { type: "action", config: { do: "notify", value: "Replied to the first email" }, next: null },
			n6: { type: "send", config: { template: "" }, next: null } } }) },
	};

	class Studio {
		constructor(page) {
			this.page = page;
			this.$root = $('<div class="aut"></div>').appendTo(page.main);
			this.cat = null;
			$(document).on("keydown.autstudio", (ev) => this.key(ev));
		}

		show() {
			const route = frappe.get_route();
			const name = route[1];
			return (this.cat ? Promise.resolve() : frappe.xcall(API + "catalog").then((c) => (this.cat = c))).then(() => (name ? this.editor(name) : this.list()));
		}

		// List ------------------------------------------------------------------

		list() {
			this.leave_editor();
			return frappe.xcall(API + "automations").then((rows) => {
				const cards = rows.map((r) => `<div class="aut-card"><div class="aut-bar"><b>${e(r.automation_name)}</b><span class="aut-badge ${e(r.status)}">${e(r.status)}</span></div>
					<div class="aut-muted">${e(r.trigger_event)}</div><div class="aut-num"><div><b>${num(r.people)}</b><span>${__("people")}</span></div><div><b>${num(r.in_progress)}</b><span>${__("in progress")}</span></div><div><b>${num(r.completed)}</b><span>${__("finished")}</span></div></div>
					<button class="btn btn-default btn-xs aut-open" data-name="${e(r.name)}">${can_manage() ? __("Open") : __("View")}</button></div>`).join("");
				this.$root.html(`<div class="aut-bar"><span class="aut-muted">${__("An automation follows people through steps: send a message, wait, branch on what they did, tag them, or hand them to your team.")}</span>
					${can_manage() ? `<button class="btn btn-primary btn-sm aut-new">${__("New automation")}</button>` : ""}</div>
					${rows.length ? `<div class="aut-grid">${cards}</div>` : `<div class="aut-card aut-empty">${__("No automations yet. Start from a ready-made flow and choose your own templates.")}</div>`}`);
				this.$root.find(".aut-new").on("click", () => this.new_dialog());
				this.$root.find(".aut-open").on("click", (ev) => frappe.set_route("automation-studio", ev.currentTarget.dataset.name));
			});
		}

		new_dialog() {
			const d = new frappe.ui.Dialog({
				title: __("New automation"),
				fields: [{ fieldname: "name", fieldtype: "Data", label: __("Name"), reqd: 1 },
					{ fieldname: "starter", fieldtype: "Select", label: __("Start from"), options: [""].concat(Object.values(STARTERS).map((x) => x.label)).join("\n") },
					{ fieldname: "event", fieldtype: "Select", label: __("Starts when"), options: Object.values(this.cat.triggers).join("\n"), default: this.cat.triggers.signup, depends_on: "eval:!doc.starter" }],
				primary_action_label: __("Create"),
				primary_action: (v) => {
					const starter = Object.values(STARTERS).find((x) => x.label === v.starter);
					const event = (Object.entries(this.cat.triggers).find(([, text]) => text === v.event) || ["signup"])[0];
					frappe.xcall(API + "create", { automation_name: v.name, event: starter ? starter.event : event }).then((name) => {
						const go = () => { d.hide(); frappe.set_route("automation-studio", name); };
						if (!starter) return go();
						return frappe.xcall(API + "save", { name, flow: starter.build() }).then(go);
					});
				},
			});
			d.show();
		}

		// Editor ----------------------------------------------------------------

		leave_editor() { clearTimeout(this.t_check); clearTimeout(this.t_save); clearInterval(this.t_stats); this.auto = null; }

		editor(name) {
			return frappe.xcall(API + "automation", { name }).then((a) => {
				this.leave_editor();
				this.auto = a; this.flow = a.flow; this.issues = a.issues; this.stats = a.stats; this.sel = null; this.zoom = Number(store.get("aut_zoom", 1)) || 1;
				this.dir = store.get("aut_dir", "v"); this.tab = "step"; this.show_stats = a.status === "Active"; this.path = []; this.decisions = {};
				this.readonly = !can_manage() || a.status === "Active";
				this.shell();
				this.paint();
				this.t_stats = setInterval(() => this.refresh_stats(), 30000);
			});
		}

		shell() {
			const a = this.auto;
			this.$root.html(`<div class="aut-top"><button class="btn btn-default btn-xs aut-back">&larr;</button>
				<input class="aut-name" value="${e(a.automation_name)}" ${can_manage() ? "" : "disabled"}><span class="aut-badge ${e(a.status)} aut-status">${e(a.status)}</span><span class="aut-saved"></span><span class="sp"></span>
				<span class="aut-tools"><button class="btn btn-default btn-xs aut-zo">&minus;</button><span class="z"></span><button class="btn btn-default btn-xs aut-zi">+</button>
				<button class="btn btn-default btn-xs aut-fit" title="F">${__("Fit")}</button><button class="btn btn-default btn-xs aut-dir" title="${__("Top to bottom, or left to right")}">${__("Layout")}</button>
				<button class="btn btn-default btn-xs aut-statbtn">${__("Numbers")}</button></span>
				${can_manage() ? `<button class="btn btn-primary btn-sm aut-act"></button>` : ""}</div>
				<div class="aut-banner" style="display:none"><span>${__("This automation is switched on. Changing it switches it off until you check it and switch it on again.")}</span><button class="btn btn-default btn-xs aut-edit">${__("Edit (switch off)")}</button></div>
				<div class="aut-work"><div class="aut-canvas"><div class="aut-world"></div></div><div class="aut-side"><nav>${[["step", __("Step")], ["problems", __("Problems")], ["simulate", __("Simulate")], ["people", __("People")]]
					.map(([k, l]) => `<button data-tab="${k}">${l}</button>`).join("")}</nav><div class="aut-pane"></div></div></div>`);
			const $r = this.$root;
			$r.find(".aut-back").on("click", () => frappe.set_route("automation-studio"));
			$r.find(".aut-name").on("change", (ev) => frappe.xcall(API + "save", { name: a.name, flow: this.flow, automation_name: ev.target.value }).then((r) => this.apply_saved(r)));
			$r.find(".aut-zi").on("click", () => this.set_zoom(this.zoom + 0.1)); $r.find(".aut-zo").on("click", () => this.set_zoom(this.zoom - 0.1));
			$r.find(".aut-fit").on("click", () => this.fit());
			$r.find(".aut-dir").on("click", () => { this.dir = this.dir === "v" ? "h" : "v"; store.set("aut_dir", this.dir); this.paint(); this.fit(); });
			$r.find(".aut-statbtn").on("click", () => { this.show_stats = !this.show_stats; this.paint(); });
			$r.find(".aut-edit").on("click", () => frappe.xcall(API + "pause", { name: a.name }).then(() => { this.auto.status = "Paused"; this.readonly = false; this.update_status(); this.paint(); }));
			$r.find(".aut-act").on("click", () => this.toggle_active());
			$r.find(".aut-side nav button").on("click", (ev) => { this.tab = ev.currentTarget.dataset.tab; this.paint_side(); });
			const $c = $r.find(".aut-canvas");
			$c.on("mousedown", (ev) => {
				if ($(ev.target).closest(".aut-node, .aut-plus").length) return;
				const start = { x: ev.clientX, y: ev.clientY, l: $c.scrollLeft(), t: $c.scrollTop() };
				$c.addClass("drag");
				const move = (m) => { $c.scrollLeft(start.l - (m.clientX - start.x)); $c.scrollTop(start.t - (m.clientY - start.y)); };
				$(document).on("mousemove.autpan", move).one("mouseup", () => { $(document).off("mousemove.autpan"); $c.removeClass("drag"); });
			});
			this.update_status();
		}

		update_status() {
			const a = this.auto;
			this.$root.find(".aut-status").attr("class", `aut-badge ${a.status} aut-status`).text(a.status);
			this.$root.find(".aut-act").text(a.status === "Active" ? __("Pause") : __("Switch on")).toggleClass("btn-primary", a.status !== "Active").toggleClass("btn-default", a.status === "Active");
			this.$root.find(".aut-banner").toggle(a.status === "Active" && can_manage());
		}

		// Flow edits ------------------------------------------------------------

		node(id) { return this.flow.nodes[id]; }
		exits(n) { return n.type === "condition" ? [["yes", n.yes], ["no", n.no]] : [["next", n.next]]; }

		parent_of(id) {
			for (const [pid, p] of Object.entries(this.flow.nodes)) for (const [slot, target] of this.exits(p)) if (target === id) return [pid, slot];
			return null;
		}

		ancestors(id) {
			const found = new Set(); let changed = true;
			while (changed) {
				changed = false;
				for (const [pid, p] of Object.entries(this.flow.nodes)) {
					if (found.has(pid)) continue;
					if (this.exits(p).some(([, t]) => t && (t === id || found.has(t)))) { found.add(pid); changed = true; }
				}
			}
			return found;
		}

		prune() {
			const seen = new Set(); const walk = (id) => { if (!id || seen.has(id) || !this.flow.nodes[id]) return; seen.add(id); this.exits(this.node(id)).forEach(([, t]) => walk(t)); };
			walk(this.flow.start);
			Object.keys(this.flow.nodes).forEach((id) => { if (!seen.has(id)) delete this.flow.nodes[id]; });
		}

		insert(parent, slot, type) {
			if (this.readonly) return;
			const id = uid(); const old = this.node(parent)[slot] || null;
			const node = { type, config: DEFAULTS[type]() };
			if (type === "condition") { node.yes = old; node.no = null; } else node.next = old;
			this.flow.nodes[id] = node; this.node(parent)[slot] = id;
			this.sel = id; this.tab = "step"; this.touch();
		}

		remove(id) {
			if (this.readonly || id === this.flow.start) return;
			const n = this.node(id); const [pid, slot] = this.parent_of(id) || [];
			const keep = n.type === "condition" ? (n.yes || n.no || null) : n.next;
			if (pid) this.node(pid)[slot] = keep;
			delete this.flow.nodes[id]; this.prune(); this.sel = null; this.touch();
		}

		touch() {
			this.paint();
			clearTimeout(this.t_check); clearTimeout(this.t_save);
			this.$root.find(".aut-saved").text(__("Not saved yet"));
			this.t_check = setTimeout(() => frappe.xcall(API + "check", { flow: this.flow }).then((r) => { this.issues = r.issues; this.paint_side(); this.paint_issue_marks(); }), 500);
			if (can_manage() && !this.readonly) this.t_save = setTimeout(() => this.save(), 1500);
		}

		save() {
			return frappe.xcall(API + "save", { name: this.auto.name, flow: this.flow }).then((r) => this.apply_saved(r));
		}

		apply_saved(r) {
			this.auto.status = r.status; this.auto.automation_name = r.automation_name; this.issues = r.issues;
			this.$root.find(".aut-saved").text(__("Saved"));
			this.update_status(); this.paint_side(); this.paint_issue_marks();
		}

		toggle_active() {
			const a = this.auto;
			if (a.status === "Active") return frappe.xcall(API + "pause", { name: a.name }).then(() => { a.status = "Paused"; this.readonly = false; this.update_status(); this.paint(); });
			if (this.issues.length) { this.tab = "problems"; this.paint_side(); frappe.show_alert({ message: __("Fix the problems first"), indicator: "orange" }); return null; }
			return this.save().then(() => frappe.confirm(__("Switch this automation on? Its messages are written as drafts and follow your approval and sending rules. People start when the trigger happens."), () =>
				frappe.xcall(API + "activate", { name: a.name }).then(() => { a.status = "Active"; this.readonly = true; this.show_stats = true; this.update_status(); this.refresh_stats(); this.paint(); frappe.show_alert({ message: __("Switched on"), indicator: "green" }); })));
		}

		// Drawing ---------------------------------------------------------------

		describe(n) {
			const c = n.config || {}; const cat = this.cat;
			const tpl = (name) => ((cat.templates || []).find((t) => t.name === name) || {}).template_name || name;
			const seg = (name) => ((cat.segments || []).find((s) => s.name === name) || {}).segment_name || name;
			if (n.type === "trigger") { const extra = c.form ? ((cat.forms || []).find((f) => f.slug === c.form) || {}).form_name || c.form : c.tag || (c.segment ? seg(c.segment) : "") || c.status; return `${cat.triggers[c.event] || __("Starts here")}${extra ? ": " + extra : ""}`; }
			if (n.type === "send") return c.template ? `${__("Send")} ${tpl(c.template)}` : __("Choose a template");
			if (n.type === "wait") return `${__("Wait")} ${c.amount} ${c.unit}`;
			if (n.type === "condition") { const what = cat.checks[c.check] || ""; const extra = c.check === "tag" ? c.tag : c.check === "segment" ? seg(c.segment) : ""; return `${__("If they")} ${what} ${extra}`.trim() + (c.wait_days && ["opened", "clicked", "replied"].includes(c.check) ? `, ${__("deciding after {0} days", [c.wait_days])}` : ""); }
			if (n.type === "action") return `${cat.actions[c.do] || ""}${c.value ? ": " + c.value : ""}`;
			return c.url ? `${__("Call")} ${c.url}` : __("Enter an address");
		}

		layout() {
			const nodes = this.flow.nodes; const pos = {}; const virt = [];
			const widths = {};
			const calc = (id) => { if (widths[id] != null) return widths[id]; widths[id] = 1; const n = nodes[id]; const k = this.exits(n).map(([, t]) => (t && nodes[t] ? calc(t) : 1)); widths[id] = n.type === "condition" ? k.reduce((a, b) => a + b, 0) : Math.max(1, k[0] || 1); return widths[id]; };
			calc(this.flow.start);
			const vert = this.dir === "v"; const stepA = (vert ? W : H) + GX, stepB = (vert ? H : W) + GY;
			const placed = new Set();
			const place = (id, left, depth, parent, slot) => {
				if (placed.has(id)) return; placed.add(id);
				const w = widths[id]; const center = left + (w * stepA) / 2 - GX / 2;
				pos[id] = vert ? { x: center - W / 2, y: PAD + depth * stepB } : { x: PAD + depth * stepB, y: center - H / 2 };
				let cursor = left;
				this.exits(nodes[id]).forEach(([s, t]) => {
					const cw = t && nodes[t] ? widths[t] : 1;
					if (t && nodes[t]) place(t, cursor, depth + 1, id, s);
					else { const c = cursor + (cw * stepA) / 2 - GX / 2; virt.push({ parent: id, slot: s, x: vert ? c : PAD + (depth + 1) * stepB + W / 2 - W / 2, y: vert ? PAD + (depth + 1) * stepB + 14 : c }); }
					cursor += cw * stepA;
				});
			};
			place(this.flow.start, PAD, 0);
			let maxX = 0, maxY = 0;
			Object.values(pos).forEach((p) => { maxX = Math.max(maxX, p.x + W); maxY = Math.max(maxY, p.y + H); });
			virt.forEach((v) => { maxX = Math.max(maxX, v.x + 40); maxY = Math.max(maxY, v.y + 40); });
			return { pos, virt, w: maxX + PAD, h: maxY + PAD };
		}

		paint() {
			if (!this.auto) return;
			const L = this.layout(); this.L = L; const vert = this.dir === "v";
			const nodes = this.flow.nodes; const bad = new Set(this.issues.map((i) => i.node)); const on = new Set(this.path.map((p) => p.node));
			const edges = []; const plus = []; const labels = [];
			const anchor = (id, out) => { const p = L.pos[id]; return vert ? { x: p.x + W / 2, y: out ? p.y + H : p.y } : { x: out ? p.x + W : p.x, y: p.y + H / 2 }; };
			const curve = (a, b) => (vert ? `M${a.x},${a.y} C${a.x},${a.y + 30} ${b.x},${b.y - 30} ${b.x},${b.y}` : `M${a.x},${a.y} C${a.x + 40},${a.y} ${b.x - 40},${b.y} ${b.x},${b.y}`);
			Object.entries(nodes).forEach(([id, n]) => {
				if (!L.pos[id]) return;
				this.exits(n).forEach(([slot, t]) => {
					if (!t || !L.pos[t]) return;
					const a = anchor(id, true), b = anchor(t, false); const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
					edges.push(`<path class="${on.has(id) && on.has(t) ? "on" : ""}" d="${curve(a, b)}"/>`);
					plus.push(`<button class="aut-plus" style="left:${mid.x}px;top:${mid.y}px" data-p="${id}" data-s="${slot}" title="${__("Insert a step here")}">+</button>`);
					if (n.type === "condition") labels.push(`<span class="aut-lbl ${slot}" style="left:${a.x + (b.x - a.x) * 0.22}px;top:${a.y + (b.y - a.y) * 0.22}px">${slot === "yes" ? __("Yes") : __("No")}</span>`);
				});
			});
			L.virt.forEach((v) => {
				const a = anchor(v.parent, true); const b = vert ? { x: v.x, y: v.y } : { x: v.x - 12, y: v.y };
				edges.push(`<path d="${curve(a, { x: vert ? v.x : v.x, y: vert ? v.y : v.y })}" stroke-dasharray="4 4"/>`);
				plus.push(`<button class="aut-plus leaf" style="left:${v.x}px;top:${v.y}px" data-p="${v.parent}" data-s="${v.slot}" title="${__("Add a step")}">+</button>`);
				if (nodes[v.parent].type === "condition") labels.push(`<span class="aut-lbl ${v.slot}" style="left:${a.x + (b.x - a.x) * 0.35}px;top:${a.y + (b.y - a.y) * 0.35}px">${v.slot === "yes" ? __("Yes") : __("No")}</span>`);
			});
			const cards = Object.entries(nodes).filter(([id]) => L.pos[id]).map(([id, n]) => {
				const k = KINDS[n.type]; const p = L.pos[id]; const st = this.stats || { reached: {}, here: {} };
				const num_html = this.show_stats && this.auto.status !== "Draft" ? `<div class="s">${num(st.reached[id] || 0)} ${__("reached")} · ${num(st.here[id] || 0)} ${__("here")}</div>` : "";
				return `<div class="aut-node ${this.sel === id ? "sel" : ""} ${bad.has(id) ? "bad" : ""} ${on.has(id) ? "on" : ""}" data-id="${id}" style="--c:${k.color};left:${p.x}px;top:${p.y}px;width:${W}px;min-height:${H}px">
					<header>${k.label}${bad.has(id) ? "<i>!</i>" : ""}</header><div class="t">${e(this.describe(n))}</div>${num_html}</div>`;
			}).join("");
			const $w = this.$root.find(".aut-world");
			$w.html(`<svg width="${L.w}" height="${L.h}">${edges.join("")}</svg>${labels.join("")}${cards}${this.readonly ? "" : plus.join("")}`)
				.css({ width: L.w, height: L.h, transform: `scale(${this.zoom})` });
			this.$root.find(".z").text(`${Math.round(this.zoom * 100)}%`);
			$w.find(".aut-node").on("click", (ev) => { this.sel = ev.currentTarget.dataset.id; this.tab = "step"; this.paint(); });
			$w.find(".aut-plus").on("click", (ev) => this.pick(ev.currentTarget.dataset.p, ev.currentTarget.dataset.s));
			this.paint_side();
		}

		paint_issue_marks() { this.paint(); }

		set_zoom(z) { this.zoom = Math.max(0.3, Math.min(1.6, Math.round(z * 10) / 10)); store.set("aut_zoom", this.zoom); this.paint(); }

		fit() {
			const $c = this.$root.find(".aut-canvas"); const z = Math.min(1, ($c.width() - 10) / this.L.w, ($c.height() - 10) / this.L.h);
			this.set_zoom(Math.max(0.3, z)); $c.scrollLeft(0).scrollTop(0);
		}

		pick(parent, slot) {
			const d = new frappe.ui.Dialog({ title: __("Add a step"), size: "large", fields: [{ fieldname: "h", fieldtype: "HTML" }] });
			d.fields_dict.h.$wrapper.html(`<div class="aut-pick">${PICK.map(([k, kind, title, text]) => `<button data-k="${k}"><span class="k" style="color:${KINDS[k].color}">${kind}</span><b>${title}</b><small>${text}</small></button>`).join("")}</div>`)
				.find("button").on("click", (ev) => { d.hide(); this.insert(parent, slot, ev.currentTarget.dataset.k); });
			d.show();
		}

		key(ev) {
			if (!this.auto || !this.$root.is(":visible") || $(ev.target).is("input, textarea, select") || ev.ctrlKey || ev.metaKey) return;
			if ((ev.key === "Delete" || ev.key === "Backspace") && this.sel) { this.remove(this.sel); ev.preventDefault(); }
			else if (ev.key === "f" || ev.key === "F") this.fit();
			else if (ev.key === "a" || ev.key === "A") { this.paint(); this.fit(); }
			else if (ev.key === "+" || ev.key === "=") this.set_zoom(this.zoom + 0.1);
			else if (ev.key === "-") this.set_zoom(this.zoom - 0.1);
			else if (ev.key === "Escape") { this.sel = null; this.paint(); }
		}

		// Side panel ------------------------------------------------------------

		paint_side() {
			if (!this.auto) return;
			this.$root.find(".aut-side nav button").each((_, b) => $(b).toggleClass("on", b.dataset.tab === this.tab));
			const label = this.$root.find('.aut-side nav button[data-tab="problems"]');
			label.text(this.issues.length ? `${__("Problems")} (${this.issues.length})` : __("Problems"));
			const $p = this.$root.find(".aut-pane");
			if (this.tab === "problems") return this.pane_problems($p);
			if (this.tab === "simulate") return this.pane_simulate($p);
			if (this.tab === "people") return this.pane_people($p);
			return this.pane_step($p);
		}

		pane_problems($p) {
			$p.html(this.issues.length ? this.issues.map((i) => `<div class="aut-issue" data-id="${e(i.node)}">${e(i.message)}</div>`).join("") : `<div class="aut-ok">${__("Everything is in place. You can switch it on.")}</div>`);
			$p.find(".aut-issue").on("click", (ev) => { const id = ev.currentTarget.dataset.id; if (this.flow.nodes[id]) { this.sel = id; this.tab = "step"; this.paint(); } });
		}

		pane_step($p) {
			const n = this.sel && this.node(this.sel);
			if (!n) return $p.html(`<div class="aut-muted">${__("Click a step to change it. Use the + buttons to add steps, and the other tabs to check problems, try a person through the flow, or see who is in it.")}</div>
				<h4>${__("Shortcuts")}</h4><div class="aut-muted">F ${__("fit")} · + − ${__("zoom")} · Delete ${__("remove the step")} · Esc ${__("deselect")}</div>`);
			const c = n.config; const dis = this.readonly ? "disabled" : "";
			const sel = (k, list, cur, text) => `<select class="form-control" data-c="${k}" ${dis}>${list.map((o) => { const v = Array.isArray(o) ? o[0] : o; const t = Array.isArray(o) ? o[1] : o; return `<option value="${e(v)}" ${v === cur ? "selected" : ""}>${e(t)}</option>`; }).join("")}</select>`;
			const inp = (k, label, type = "text", extra = "") => `<label>${label}<input class="form-control" type="${type}" data-c="${k}" value="${e(c[k])}" ${extra} ${dis}></label>`;
			let body = "";
			if (n.type === "trigger") {
				body = `<label>${__("Starts when")}${sel("event", Object.entries(this.cat.triggers), c.event)}</label>`;
				if (c.event === "signup") body += `<label>${__("Only this form (optional)")}${sel("form", [["", __("Any form")]].concat(this.cat.forms.map((f) => [f.slug, f.form_name])), c.form)}</label>`;
				if (c.event === "tag_added") body += inp("tag", __("Tag"));
				if (c.event === "segment_joined") body += `<label>${__("Segment")}${sel("segment", [["", __("Choose…")]].concat(this.cat.segments.map((s) => [s.name, s.segment_name])), c.segment)}</label><div class="aut-muted">${__("Everyone in the segment starts, and so does anyone who joins later (checked every half hour).")}</div>`;
				if (c.event === "deal_stage") body += `<label>${__("Stage (optional)")}${sel("status", [["", __("Any stage")]].concat(this.cat.deal_statuses), c.status)}</label>`;
				if (["api_call", "manual"].includes(c.event)) body += `<div class="aut-muted">${c.event === "manual" ? __("You enrol people by hand or from a segment, on the automation's page.") : __("Your system starts it for a person with the API: reckon_sales_agent.api_automation.trigger.")}</div>`;
				body += `<label class="aut-muted"><input type="checkbox" data-c="reenter" ${c.reenter ? "checked" : ""} ${dis}> ${__("Let the same person go through it again")}</label>`;
			} else if (n.type === "send") {
				body = `<label>${__("Template")}${sel("template", [["", __("Choose…")]].concat(this.cat.templates.map((t) => [t.name, `${t.template_name} (${t.channel})`])), c.template)}</label>
					<div class="aut-muted">${__("Only approved Email, SMS and WhatsApp templates are listed. The message is written as a draft for the person, and follows your approval, consent, sending hours and pacing rules.")}</div>`;
			} else if (n.type === "wait") {
				body = `<div class="aut-two">${inp("amount", __("For"), "number", 'min="1"')}<label>${__("Unit")}${sel("unit", this.cat.units, c.unit)}</label></div>`;
			} else if (n.type === "condition") {
				const sends = [["any", __("Any message in this flow")]].concat([...this.ancestors(this.sel)].filter((id) => this.node(id).type === "send").map((id) => [id, this.describe(this.node(id))]));
				body = `<label>${__("Check whether they")}${sel("check", Object.entries(this.cat.checks), c.check)}</label>`;
				if (["opened", "clicked", "replied"].includes(c.check)) body += `<label>${__("Which message")}${sel("ref", sends, c.ref)}</label>${inp("wait_days", __("Wait up to (days) before saying No"), "number", 'min="0" max="30"')}`;
				if (c.check === "tag") body += inp("tag", __("Tag"));
				if (c.check === "segment") body += `<label>${__("Segment")}${sel("segment", [["", __("Choose…")]].concat(this.cat.segments.map((s) => [s.name, s.segment_name])), c.segment)}</label>`;
			} else if (n.type === "action") {
				body = `<label>${__("Do this")}${sel("do", Object.entries(this.cat.actions), c.do)}</label>`;
				if (c.do !== "stop") body += inp("value", ["add_tag", "remove_tag"].includes(c.do) ? __("Tag") : c.do === "create_task" || c.do === "notify" ? __("Task title") : __("Value"));
			} else if (n.type === "webhook") {
				body = `${inp("url", __("Address (https)"))}<div class="aut-muted">${__("Sends the person's id, email, phone, name and tags as JSON. Add a signing secret on the automation to sign the call (header X-Reckon-Signature).")}</div>`;
			}
			const mine = this.issues.filter((i) => i.node === this.sel).map((i) => `<div class="aut-issue">${e(i.message)}</div>`).join("");
			$p.html(`<h4>${KINDS[n.type].label}</h4>${body}${mine}${this.readonly || n.type === "trigger" ? "" : `<button class="btn btn-default btn-xs aut-rm">${__("Remove this step")}</button>`}`);
			$p.find("[data-c]").on("input change", (ev) => {
				const k = ev.currentTarget.dataset.c; let v = ev.currentTarget.type === "checkbox" ? ev.currentTarget.checked : ev.currentTarget.value;
				if (ev.currentTarget.type === "number") v = Number(v || 0);
				c[k] = v;
				if (ev.type === "change") this.touch(); else this.paint_cards_only();
			});
			$p.find(".aut-rm").on("click", () => this.remove(this.sel));
		}

		paint_cards_only() { // while typing: refresh the cards without rebuilding the side form
			Object.entries(this.flow.nodes).forEach(([id, n]) => this.$root.find(`.aut-node[data-id="${id}"] .t`).text(this.describe(n)));
		}

		pane_simulate($p) {
			const conds = Object.entries(this.flow.nodes).filter(([, n]) => n.type === "condition");
			$p.html(`<div class="aut-muted">${__("Follow one person through the flow. Nothing is sent or changed.")}</div>
				${conds.map(([id, n]) => `<label class="aut-muted">${e(this.describe(n))}<select class="form-control aut-dec" data-id="${id}"><option value="1" ${this.decisions[id] === false ? "" : "selected"}>${__("Yes")}</option><option value="0" ${this.decisions[id] === false ? "selected" : ""}>${__("No")}</option></select></label>`).join("")}
				<button class="btn btn-primary btn-xs aut-sim">${__("Show the path")}</button><div class="aut-sim-out" style="margin-top:10px"></div>`);
			$p.find(".aut-dec").on("change", (ev) => { this.decisions[ev.currentTarget.dataset.id] = ev.currentTarget.value === "1"; });
			$p.find(".aut-sim").on("click", () => frappe.xcall(API + "simulate", { flow: this.flow, decisions: this.decisions }).then((r) => {
				this.path = r.path; this.paint(); this.tab = "simulate";
				this.$root.find(".aut-pane .aut-sim-out").html(`${r.path.map((s) => `<div class="aut-step"><b>${e(s.when)}</b><span>${e(s.label)}${s.answer === null ? "" : ` → <b>${s.answer ? __("Yes") : __("No")}</b>`}</span></div>`).join("")}<div class="aut-muted" style="margin-top:6px">${__("Finishes after {0}.", [e(r.total)])}</div>`);
			}));
		}

		pane_people($p) {
			$p.html(`<div class="aut-muted">${__("Loading…")}</div>`);
			frappe.xcall(API + "runs", { name: this.auto.name }).then((rows) => {
				const st = this.stats;
				const enrol = this.auto.status === "Active" && can_manage() ? `<div class="aut-two" style="margin-bottom:8px"><button class="btn btn-default btn-xs aut-enrol-seg">${__("Enrol a segment")}</button><button class="btn btn-default btn-xs aut-enrol-one">${__("Enrol one person")}</button></div>` : "";
				$p.html(`${enrol}<div class="aut-muted">${st ? `${num(st.total)} ${__("people")}: ${Object.entries(st.by_status).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(", ") || __("none yet")}` : ""}</div>
					${rows.map((r) => `<div class="aut-step"><span class="aut-badge ${r.status === "Stopped" ? "bad" : r.status === "Completed" ? "Active" : ""}">${e(r.status)}</span><span>${e(r.person)}<div class="aut-muted">${e(r.email || "")}${r.reason ? " · " + e(r.reason) : ""}${r.next_check ? " · " + __("next check {0}", [frappe.datetime.prettyDate(r.next_check)]) : ""}</div></span></div>`).join("")}`);
				$p.find(".aut-enrol-seg").on("click", () => frappe.prompt([{ fieldname: "segment", fieldtype: "Select", label: __("Segment"), options: this.cat.segments.map((s) => `${s.name}`).join("\n"), reqd: 1 }], (v) =>
					frappe.xcall(API + "enroll_segment", { name: this.auto.name, segment: v.segment }).then((r) => { frappe.show_alert({ message: __("{0} enrolled, {1} skipped", [r.enrolled, r.skipped]), indicator: "green" }); this.refresh_stats(); }), __("Enrol a segment")));
				$p.find(".aut-enrol-one").on("click", () => frappe.prompt([{ fieldname: "email", fieldtype: "Data", label: __("Email"), reqd: 1 }], (v) =>
					frappe.xcall(API + "enroll_person", { name: this.auto.name, email: v.email }).then((r) => frappe.show_alert({ message: r.enrolled ? __("Enrolled") : __("Already in, or opted out"), indicator: r.enrolled ? "green" : "orange" })), __("Enrol one person")));
			});
		}

		refresh_stats() {
			if (!this.auto || !this.$root.is(":visible")) return null;
			return frappe.xcall(API + "automation", { name: this.auto.name }).then((a) => { this.stats = a.stats; this.paint(); });
		}
	}
})();
