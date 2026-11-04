"""Public tracking endpoint: the 1x1 image in an email records that the message was opened.

Clicks use the ``/l/<code>`` page (www/l.py). Neither endpoint reveals anything: the code only points to a stored row, and
a code that does not exist gets the same empty image or a plain 404.
"""

import frappe
from werkzeug.wrappers import Response

from reckon_sales_agent.campaigns import tracking


@frappe.whitelist(allow_guest=True, methods=["GET"])
def open_pixel(c: str = ""):
    from reckon_sales_agent.campaigns.track_links import opened

    try:
        opened(str(c or "")[:32], frappe.get_request_header("User-Agent"))
    except Exception:
        frappe.db.rollback()
        frappe.log_error(title="Sales Agent open tracking failed")
    # Always the same image, so a wrong code teaches a visitor nothing.
    return Response(tracking.GIF, mimetype="image/gif",
                    headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache"})
