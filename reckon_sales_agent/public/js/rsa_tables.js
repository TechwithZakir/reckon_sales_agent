/* One way to make a list of rows searchable, sortable and paged (ten at a time).
 *
 *   rsa_tables.enhance($container, { rows: "tbody > tr", head: "thead th", size: 10, search: true, sort: true })
 *
 * The rows can be table rows or the grid rows some Studio pages use. Call it again after the rows are replaced and it
 * keeps the toolbar and starts over with the new rows. It only shows and hides rows, so click handlers on them keep
 * working. Nothing here talks to the server.
 */
(function () {
	"use strict";
	if (!window.frappe) return;

	if (!document.getElementById("rsa-tables-css")) {
		const style = document.createElement("style");
		style.id = "rsa-tables-css";
		style.textContent = `
.rsa-tbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 0 0 8px; }
.rsa-tbar .rsa-q { flex: 1 1 200px; min-width: 140px; }
.rsa-tbar select { width: auto; }
.rsa-tpager { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px; margin: 8px 0 0; font-size: 12px; }
.rsa-tpages { display: inline-flex; gap: 4px; align-items: center; }
.rsa-tnone { display: none; padding: 14px 4px; color: var(--text-muted, #6b7280); font-size: 13px; }
.rsa-sortable { cursor: pointer; user-select: none; }
.rsa-sortable::after { content: " ⇅"; opacity: .35; font-size: 10px; }
.rsa-sortable.asc::after { content: " ▲"; opacity: .8; }
.rsa-sortable.desc::after { content: " ▼"; opacity: .8; }
`;
		document.head.appendChild(style);
	}

	const numeric = (text) => {
		const m = String(text).replace(/,/g, "").match(/-?\d+(\.\d+)?/);
		return m ? parseFloat(m[0]) : NaN;
	};

	function enhance($root, opts) {
		$root = $($root);
		if (!$root.length) return null;
		const existing = $root.data("rsa-tbl");
		if (existing) {
			existing.reset();
			return existing;
		}
		opts = Object.assign({ size: 10, rows: "tbody > tr", head: "thead th", search: true, sort: true }, opts || {});
		const st = { q: "", page: 1, size: opts.size, col: -1, dir: 1 };
		const sizes = [...new Set([5, 10, 25, 50, 100, opts.size])].sort((a, b) => a - b);
		const $bar = $(`<div class="rsa-tbar">
			${opts.search ? `<input type="search" class="form-control input-sm rsa-q" placeholder="${__("Search")}" aria-label="${__("Search")}">` : ""}
			<select class="form-control input-sm rsa-size" aria-label="${__("Rows per page")}">${sizes.map((n) => `<option value="${n}" ${n === st.size ? "selected" : ""}>${__("{0} per page", [n])}</option>`).join("")}</select>
		</div>`).insertBefore($root);
		const $none = $(`<div class="rsa-tnone">${__("Nothing matches your search.")}</div>`).insertAfter($root);
		const $pager = $('<div class="rsa-tpager"><span class="text-muted rsa-tinfo"></span><span class="rsa-tpages"></span></div>').insertAfter($none);

		const rows = () => $root.find(opts.rows).filter((_, r) => !$(r).find("td[colspan]").length).toArray();

		function paint() {
			const all = rows();
			all.forEach((r, i) => { if (r.dataset.rsaI == null) r.dataset.rsaI = String(i); });
			if (all.length) {
				// Sorted by a column, or back to the order the rows arrived in.
				const sorted = all.slice().sort((a, b) => {
					if (st.col < 0) return Number(a.dataset.rsaI) - Number(b.dataset.rsaI);
					const x = $(a).children().eq(st.col).text().trim();
					const y = $(b).children().eq(st.col).text().trim();
					const nx = numeric(x), ny = numeric(y);
					const cmp = !isNaN(nx) && !isNaN(ny) && nx !== ny ? nx - ny : x.localeCompare(y, undefined, { numeric: true });
					return (cmp || Number(a.dataset.rsaI) - Number(b.dataset.rsaI)) * (st.col < 0 ? 1 : st.dir);
				});
				const parent = all[0].parentNode;
				sorted.forEach((r) => parent.appendChild(r));
				all.length = 0;
				sorted.forEach((r) => all.push(r));
			}
			const q = st.q.trim().toLowerCase();
			const hits = q ? all.filter((r) => r.textContent.toLowerCase().includes(q)) : all;
			const pages = Math.max(1, Math.ceil(hits.length / st.size));
			st.page = Math.min(Math.max(1, st.page), pages);
			const from = (st.page - 1) * st.size;
			const visible = new Set(hits.slice(from, from + st.size));
			all.forEach((r) => { r.style.display = visible.has(r) ? "" : "none"; });
			$bar.toggle(all.length > 0);
			$none.toggle(all.length > 0 && hits.length === 0);
			$pager.toggle(hits.length > 0);
			$pager.find(".rsa-tinfo").text(hits.length ? __("{0}–{1} of {2}", [from + 1, Math.min(from + st.size, hits.length), hits.length]) : "");
			const near = [...new Set([1, pages, st.page - 1, st.page, st.page + 1])].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
			let last = 0;
			const btn = (label, to, cls, off) => `<button type="button" class="btn btn-xs btn-default rsa-tpg ${cls || ""}" data-page="${to}" ${off ? "disabled" : ""}>${label}</button>`;
			$pager.find(".rsa-tpages").html(pages <= 1 ? "" : btn("‹", st.page - 1, "", st.page === 1)
				+ near.map((n) => { const gap = n - last > 1 ? '<span class="text-muted">…</span>' : ""; last = n; return gap + btn(n, n, n === st.page ? "btn-primary" : ""); }).join("")
				+ btn("›", st.page + 1, "", st.page === pages));
		}

		$bar.on("input", ".rsa-q", (ev) => { st.q = ev.currentTarget.value; st.page = 1; paint(); });
		$bar.on("change", ".rsa-size", (ev) => { st.size = Number(ev.currentTarget.value) || 10; st.page = 1; paint(); });
		$pager.on("click", ".rsa-tpg:not([disabled])", (ev) => { st.page = Number(ev.currentTarget.dataset.page); paint(); });
		// The header cells may be rebuilt along with the rows, so this runs again on every reset.
		function bindHeads() {
			if (!(opts.sort && opts.head)) return;
			$root.find(opts.head).each((i, th) => {
				const $th = $(th);
				if ($th.find("input").length || !$th.text().trim()) return;
				$th.removeClass("asc desc").addClass("rsa-sortable").attr({ role: "button", tabindex: 0, title: __("Sort") })
					.off("click.rsa keydown.rsa").on("click.rsa keydown.rsa", (ev) => {
						if (ev.type === "keydown" && ev.key !== "Enter" && ev.key !== " ") return;
						ev.preventDefault();
						st.dir = st.col === i ? -st.dir : 1;
						st.col = i;
						$root.find(opts.head).removeClass("asc desc");
						$th.addClass(st.dir === 1 ? "asc" : "desc");
						st.page = 1;
						paint();
					});
				if (st.col === i) $th.addClass(st.dir === 1 ? "asc" : "desc");
			});
		}

		const tbl = {
			paint,
			// New rows have arrived: keep the search and the sort, go back to the first page.
			reset() { st.page = 1; $root.find(opts.rows).each((_, r) => { delete r.dataset.rsaI; }); bindHeads(); paint(); },
		};
		$root.data("rsa-tbl", tbl);
		bindHeads();
		paint();
		return tbl;
	}

	window.rsa_tables = { enhance };
})();
