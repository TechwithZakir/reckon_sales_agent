"""Sales Analytics first in the menu, the Campaign group, and Messages sent under it (the menu Desk shows is a Sidebar record)."""

from reckon_sales_agent.install import sync_sidebar_record


def execute():
    sync_sidebar_record()
