"""The agent's toolset.

Every tool the agent can call is assembled here. All of them now return real
data — the mocks that stood in during early sprints have been replaced one by
one, each keeping the name, signature and description of the mock it replaced
so the agent's tool-selection behaviour never changed with the swap.
"""

from agent.tools.financial import market_data  # real (yfinance)
from agent.tools.pdf_reader import read_pdf  # real (PyMuPDF)
from agent.tools.reader import read_page  # real (Jina AI Reader)
from agent.tools.search import news_search, web_search  # real (Tavily)

ALL_TOOLS = [web_search, news_search, read_page, read_pdf, market_data]
TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}

# Which tools return real data — used to flag mock evidence to the user.
# Every tool now returns real data; nothing is mocked.
REAL_TOOLS = {t.name for t in ALL_TOOLS}
