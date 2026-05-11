# tools.py
import requests
from typing import List, Dict
import arxiv
from pydantic import BaseModel

WEATHER_API="4e3293c6ec164e738a844511260803"

# -----------------------------
# Paper Model
# -----------------------------
class Paper(BaseModel):
    title: str
    authors: List[str]
    summary: str
    link: str


# -----------------------------
# ArXiv Search Tool
# -----------------------------
def search_papers(topic: str, max_results: int = 3) -> List[Paper]:
    print("\n", 30 * "#", "\n\tCalling Search Paper tool\n", 30 * "#", "\n")
    print(f"parameters are {topic} and {max_results}\n\n")
    if isinstance(max_results, str):
        max_results = int(max_results)
    
    client_arxiv = arxiv.Client(page_size=max_results)
    search = arxiv.Search(
        query=topic,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance
    )

    results = []
    for paper in client_arxiv.results(search):
        results.append(Paper(
            title=paper.title,
            authors=[a.name for a in paper.authors],
            summary=paper.summary,
            link=paper.entry_id
        ))

    print("\n\n",30*"*")
    for paper in results:
        print(f"Title: {paper.title}\nAuthors: {paper.authors}\nSummary: {paper.summary}\nLink: {paper.link}\n")
    print(30*"*", "\n\n")
    return results  


# -----------------------------
# Weather Tool
# -----------------------------
def get_weather(city: str) -> dict:
    print("\n", 30 * "#", f"\n\tCalling Weather tool for {city}\n", 30 * "#", "\n")

    url = f"http://api.weatherapi.com/v1/current.json?key={WEATHER_API}&q={city}"
    response = requests.get(url)
    data = response.json()
    print(30*"*")
    print(f"\nThe current temperature in {city} is {data['current']['temp_c']} degrees Celsius.\n")
    print(30*"*")
    return {
        "city": data["location"]["name"],
        "temperature": data["current"]["temp_c"],
        "humidity": data["current"]["humidity"],
        "description": data["current"]["condition"]["text"]
    }


# -----------------------------
# Web Search Tool (DuckDuckGo)
# -----------------------------
from bs4 import BeautifulSoup

def web_search(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    print("\n", 30 * "#", "\n\tCalling Web Search tool\n", 30 * "#", "\n")

    try:
        url = "https://duckduckgo.com/html/"
        params = {"q": query}

        headers = {"User-Agent": "Mozilla/5.0"}

        response = requests.post(url, data=params, headers=headers, timeout=10)

        if response.status_code != 200:
            return [{"error": f"Request failed: {response.status_code}"}]

        soup = BeautifulSoup(response.text, "html.parser")

        results = []
        items = soup.find_all("div", class_="result", limit=max_results)

        for item in items:
            title_tag = item.find("a", class_="result__a")
            snippet_tag = item.find("a", class_="result__snippet")

            if not title_tag:
                continue

            results.append({
                "title": title_tag.get_text(strip=True),
                "link": title_tag.get("href", ""),
                "snippet": snippet_tag.get_text(strip=True) if snippet_tag else ""
            })

        return results

    except Exception as e:
        return [{"error": str(e)}]