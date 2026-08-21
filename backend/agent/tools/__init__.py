"""The agent's toolset.

Real tools and remaining mocks are assembled here so the rest of the code never
needs to know which is which. Replacing a mock is a one-line change in this
file — the agent's decision-making is unaffected, since names, signatures and
descriptions stay identical across the swap.
"""

from agent.tools.mock import financial_data  # Sprint 10
from agent.tools.pdf_reader import read_pdf  # real (PyMuPDF)
from agent.tools.reader import read_page  # real (Jina AI Reader)
from agent.tools.search import news_search, web_search  # real (Tavily)

ALL_TOOLS = [web_search, news_search, read_page, read_pdf, financial_data]
TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}

# Which tools return real data — used to flag mock evidence to the user.
REAL_TOOLS = {"web_search", "news_search", "read_page", "read_pdf"}
