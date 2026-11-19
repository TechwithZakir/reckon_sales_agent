/* "Limits and capacity": what the Sales Agent may do, what it has used and what is waiting, shown on screen.
 *
 *   rsa_limits.mount($host, ["capture", "ai", "sending"])
 *
 * Reads one endpoint, draws meters (green, amber at 80 percent, red when full) and refreshes itself while the host is on
 * the page. A failure here only hides the panel; it never breaks the page it sits on.
 */
(function () {
	"use strict";
	if (!window.frappe) return;

	const API = "reckon_sales_agent.api_limits.overview";
	const e = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const num = (v) => Number(v || 0).toLocaleString();

	if (!document.getElementById("rsa-limits-css")) {
		const style = document.createElement("style");
		style.id = "rsa-limits-css";
		style.textContent = `
.rsl { background: var(--aura-surface, var(--card-bg, #fff)); border: 1px solid var(--aura-line, var(--border-color, #e3e5ea)); border-radius: 14px; padding: 12px 16px; margin: 0 0 14px; }
.rsl > summary { cursor: pointer; font-weight: 600; font-size: 13px; text-transform: uppercase; letter-spacing: .04em; color: var(--aura-muted, var(--text-muted, #6b7280)); }
.rsl-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px 22px; margin-top: 10px; }
.rsl-group h5 { margin: 0 0 8px; font-family: var(--aura-font, inherit); font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; color: var(--aura-muted, var(--text-muted, #6b7280)); }
.rsl-m { margin-bottom: 9px; }
.rsl-m .rsl-r { display: flex; justify-content: space-between; gap: 8px; font-size: 12.5px; }
.rsl-m .rsl-r b { font-weight: 600; }
.rsl-bar { height: 7px; border-radius: 999px; background: color-mix(in srgb, var(--aura-accent, #6d4cff) 12%, transparent); overflow: hidden; margin-top: 3px; }
.rsl-bar i { display: block; height: 100%; border-radius: 999px; background: var(--aura-accent, #6d4cff); }
.rsl-m.warn .rsl-bar i { background: #d97706; } .rsl-m.full .rsl-bar i { background: #dc2626; }
.rsl-note { font-size: 12px; color: var(--aura-muted, var(--text-muted, #6b7280)); margin: 2px 0 6px; }
.rsl-note.warn { color: #b45309; } .rsl-note.bad { color: #b91c1c; font-weight: 600; }
`;
		document.head.appendChild(style);
	}

	const meter = (label, m, hint) => {
		const limit = Number((m || {}).limit || 0), used = Number((m || {}).used || 0);
		const pct = limit ? Math.min(100, Math.round((100 * used) / limit)) : 0;
		const cls = limit && used >= limit ? "full" : pct >= 80 ? "warn" : "";
		return `<div class="rsl-m ${cls}" title="${e(hint || "")}"><div class="rsl-r"><span>${e(label)}</span><b>${num(used)}${limit ? ` / ${num(limit)}` : ""}</b></div>
			${limit ? `<div class="rsl-bar"><i style="width:${pct}%"></i></div>` : ""}</div>`;
	};

	const group = (title, body) => `<div class="rsl-group"><h5>${e(title)}</h5>${body}</div>`;

	const capture = (c) => {
		const eta = c.research_waiting
			? (c.eta_minutes == null ? __("{0} lead(s) are waiting for research.", [num(c.research_waiting)])
				: __("{0} lead(s) are waiting for research: about {1} minute(s) at the current pace.", [num(c.research_waiting), num(c.eta_minutes)]))
			: __("No research is waiting.");
		const workers = !c.workers.known ? "" : !c.workers.long ? `<div class="rsl-note bad">${__("No background worker is running, so nothing will finish. Ask your administrator to start the workers.")}</div>`
			: `<div class="rsl-note">${(c.workers.long_workers || 0) > 1 ? __("{0} background workers run long jobs, one each.", [num(c.workers.long_workers)]) : __("One background worker runs discovery and research, one job at a time, so discovery waits behind research.")}</div>`;
		return group(__("Lead capture"), `${meter(__("Leads this month"), c.leads, __("Your plan's monthly allowance for new leads"))}
			${meter(__("Websites researched this month"), c.research)}
			${meter(__("Discovery jobs at once"), { used: c.jobs.active, limit: c.jobs.max }, __("Jobs running or waiting, against what your plan runs at the same time"))}
			<div class="rsl-note">${__("Up to {0} leads in one run.", [num(c.per_run_max)])}</div>
			<div class="rsl-note ${c.research_waiting > 20 ? "warn" : ""}">${e(eta)}</div>${workers}`);
	};

	const ai = (a) => group(__("AI"), `<div class="rsl-note">${e(a.label || __("AI is not set up"))}</div>
		${a.enabled ? meter(__("AI calls this month"), a.calls, __("Each AI judgement or research summary is one call")) : `<div class="rsl-note warn">${__("AI is switched off for your company.")}</div>`}
		${a.paused ? `<div class="rsl-note bad">${__("AI is paused: {0}", [e(a.paused)])}</div>` : ""}`);

	const sending = (s) => group(__("Sending"), `<div class="rsl-note ${s.live ? "warn" : ""}">${s.live ? __("Sending is live: approved messages are delivered.") : __("Dry run: approved messages are recorded, not delivered.")}</div>
		${meter(__("Messages today"), s.today, s.warmup ? __("Warm-up is on, so today's real limit may be lower") : "")}
		${s.today.email_limit && s.today.email_limit < s.today.limit ? `<div class="rsl-note warn">${__("Email today: up to {0} (warm-up or your email plan).", [num(s.today.email_limit)])}</div>` : ""}
		${meter(__("Messages in the last hour"), s.hour)}
		${meter(__("Messages this month"), s.month)}`);

	const render = (data, sections, open) => `<details class="rsl" ${open ? "open" : ""}><summary>${__("Limits and capacity")}</summary>
		<div class="rsl-grid">${sections.map((k) => ({ capture, ai, sending }[k]([data.capture, data.ai, data.sending][["capture", "ai", "sending"].indexOf(k)]))).join("")}</div></details>`;

	function mount($host, sections) {
		$host = $($host);
		if (!$host.length) return null;
		const key = `rsl_open_${sections.join("_")}`;
		let open = true;
		try { open = localStorage.getItem(key) !== "0"; } catch (err) { /* private window */ }
		let timer = null;
		const paint = () => {
			if (!document.body.contains($host[0])) { clearInterval(timer); return; }
			frappe.xcall(API).then((data) => {
				$host.html(render(data, sections, open));
				$host.find("details").on("toggle", (ev) => {
					open = ev.currentTarget.open;
					try { localStorage.setItem(key, open ? "1" : "0"); } catch (err) { /* private window */ }
				});
			}).catch(() => $host.empty());
		};
		paint();
		timer = setInterval(paint, 20000);
		return { refresh: paint };
	}

	window.rsa_limits = { mount };
})();
