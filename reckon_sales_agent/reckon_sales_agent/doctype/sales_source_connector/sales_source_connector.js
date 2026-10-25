frappe.ui.form.on("Sales Source Connector", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Check Connector"), () =>
			frappe.call("reckon_sales_agent.api.check_connector", { connector: frm.doc.name }).then((r) => {
				const result = r.message || {};
				frappe.msgprint({
					title: __(result.status || ""),
					message: frappe.utils.escape_html(result.error || __("The connector is ready to run.")),
					indicator: result.error ? "orange" : "green",
				});
				frm.reload_doc();
			})
		);
		if (frm.doc.connector_type === "manual_import") {
			frm.set_intro(__("Attach a CSV file with columns business_name, website, email, phone, industry, address, city, country."), "blue");
		}
		const maps = {
			serpapi_google_maps: __("SerpAPI runs the Google Maps search and returns JSON."),
			scrapingdog_google_maps: __("Scrapingdog runs the Google Maps search and returns JSON."),
			apify_google_maps: __("Apify's Google Maps scraper actor runs the search; runs can take a few minutes."),
			google_maps_browser_experimental: __("EXPERIMENTAL headless browser on Google Maps. Unsupported by Google and restricted by its terms; stops when Google blocks it."),
		};
		if (maps[frm.doc.connector_type]) {
			frm.set_intro(maps[frm.doc.connector_type] + " " +
				__("Keys and permission are set by the platform vendor. Maps data is kept only for the vendor's retention window unless the company's website confirms it."),
				frm.doc.connector_type.endsWith("experimental") ? "orange" : "blue");
		}
		const search = {
			brave_web_search: __("Brave's official search API runs the search; results that are a business's own website become leads."),
			brave_place_search: __("Brave Place Search finds local businesses (name, website, phone, address, rating) around the search location."),
			brave_llm_context: __("Brave LLM Context returns search results with text from each page, so phones and emails come from the page itself."),
			scrapingdog_google_search: __("Scrapingdog runs the Google search; results that are a business's own website become leads."),
			scrapingbee_google_search: __("ScrapingBee runs the Google search; results that are a business's own website become leads."),
			serpapi_google_search: __("SerpAPI runs the Google search; results that are a business's own website become leads."),
			google_search_browser_experimental: __("EXPERIMENTAL headless browser on google.com. Unsupported by Google and restricted by its terms; Google blocks server traffic quickly and the run stops when it does."),
		};
		if (search[frm.doc.connector_type]) {
			frm.set_intro(search[frm.doc.connector_type] + " " +
				__("Social, marketplace, directory and news sites are skipped. Keys and permission are set by the platform vendor."),
				frm.doc.connector_type.endsWith("experimental") ? "orange" : "blue");
		}
		if (frm.doc.connector_type === "google_places_api") {
			frm.set_intro(__("Uses the official Google Places API with the platform's key. Google content is kept only for the platform's retention window unless the company's own website confirms it."), "blue");
		}
	},
});
