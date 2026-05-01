import requests
from bs4 import BeautifulSoup

class NHLGameScraper:
    def __init__(self):
        self.url = 'https://www.espn.com/nhl/schedule'

    def fetch_schedule(self):
        response = requests.get(self.url)
        soup = BeautifulSoup(response.content, 'html.parser')
        games = []

        # Scraping logic here
        for game in soup.find_all('div', class_='Schedule__Game-Item'):  # Example class, will need to adjust based on the actual page structure
            title = game.find('span', class_='Schedule__Title').text
            date_time = game.find('span', class_='Schedule__DateTime').text
            odds = self.fetch_odds(title)
            games.append({'title': title, 'date_time': date_time, 'odds': odds})
        return games

    def fetch_odds(self, game_title):
        # Dummy implementation, replace with actual logic to fetch odds
        return {'home': 1.5, 'away': 2.0}

if __name__ == '__main__':
    scraper = NHLGameScraper()
    schedule = scraper.fetch_schedule()
    print(schedule)