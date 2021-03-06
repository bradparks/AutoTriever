
import re
import calendar
import traceback
import datetime
import time
import json
import random
import selenium.common.exceptions
import bs4

import sqlalchemy.exc

import mmh3
from . import LogBase
from  . import database as db

from . import AmqpInterface
from util import WebRequest

MIN_RATING = 5

########################################################################################################################
#
#	##     ##    ###    #### ##    ##     ######  ##          ###     ######   ######
#	###   ###   ## ##    ##  ###   ##    ##    ## ##         ## ##   ##    ## ##    ##
#	#### ####  ##   ##   ##  ####  ##    ##       ##        ##   ##  ##       ##
#	## ### ## ##     ##  ##  ## ## ##    ##       ##       ##     ##  ######   ######
#	##     ## #########  ##  ##  ####    ##       ##       #########       ##       ##
#	##     ## ##     ##  ##  ##   ###    ##    ## ##       ##     ## ##    ## ##    ##
#	##     ## ##     ## #### ##    ##     ######  ######## ##     ##  ######   ######
#
########################################################################################################################


class NUSeriesUpdateFilter(LogBase.LoggerMixin):

	loggerPath = "Main.NovelUpdates.Series"

	# This plugin doesn't need AMQP connectivity at all.
	_needs_amqp = False


	def __init__(self, db_sess, settings):
		super().__init__()

		self.settings = settings
		# self.db_sess = db_sess
		self.amqp = AmqpInterface.RabbitQueueHandler(settings)
		self.wg = WebRequest.WebGetRobust(cloudflare=True)


##################################################################################################################################
##################################################################################################################################
##################################################################################################################################


	def extractSeriesReleases(self, currentUrl, soup):

		container = soup.find('div', class_='l-content')
		# print("container: ", container)

		release_tables = container.find_all('table', class_='tablesorter')

		# print("Release tables:", release_tables)

		releases = []
		for table_div in release_tables:
			for item in table_div.find_all("tr"):
				tds = item.find_all('td')
				if len(tds) == 3:
					series, release, group = tds

					release = {
						'seriesname'       : series.get_text().strip(),
						'releaseinfo'      : release.get_text().strip(),
						'groupinfo'        : group.get_text().strip(),
						'referrer'         : currentUrl,
						'outbound_wrapper' : release.find('a', class_='chp-release')['href'],
						'actual_target'    : None,

						'client_id'        : self.settings['clientid'],
						'client_key'       : self.settings['client_key'],
					}
					releases.append(release)

		return releases


	# def extractSeriesReleases_wln(self, currentUrl, soup):

	# 	# print("container: ", container)

	# 	main, oel, dummy_rss = soup.find_all('table', class_='fullwidth')

	# 	# print("Release tables:", release_tables)

	# 	releases = []
	# 	for table_div in [main, oel]:
	# 		for item in table_div.find_all("tr", id='release-entry'):
	# 			tds = item.find_all('td')

	# 			if len(tds) == 4:
	# 				link, series, chap, extra = tds
	# 				vol = None
	# 				group = None
	# 				tl_type = "oel"
	# 			elif len(tds) == 5:
	# 				if table_div == main:
	# 					link, series, chap, extra, group = tds
	# 					vol = None
	# 					tl_type = "translated"
	# 				elif table_div == oel:
	# 					link, series, vol, chap, extra = tds
	# 					group = None
	# 					tl_type = "oel"

	# 			elif len(tds) == 6:
	# 				link, series, vol, chap, extra, group = tds
	# 				tl_type = "translated"

	# 			release = {
	# 				'seriesname'       : series.get_text().strip(),
	# 				'releaseinfo'      : 'v' + str(vol.get_text().strip()   if vol and vol.get_text().strip()     else  0) +
	# 				                     'c' + str(chap.get_text().strip()  if chap and chap.get_text().strip()   else  0) +
	# 				                     ' ' + str(extra.get_text().strip() if extra and extra.get_text().strip() else ''),
	# 				'groupinfo'        : group.get_text().strip() if group else '',
	# 				'referrer'         : currentUrl,
	# 				'outbound_wrapper' : link.a['href'],
	# 				'actual_target'    : None,
	# 			}
	# 			releases.append(release)

	# 	return releases


	def fetchPage(self, url):
		content, dummy_fname, dummy_mime = self.wg.getItemPhantomJS(url)
		return content

	def processPage(self, url, content):
		soup = WebRequest.as_soup(content)
		releases = self.extractSeriesReleases(url, soup)
		relcnt = len(releases)
		if relcnt > 0:
			self.log.info("Found %s Releases.", relcnt)
		else:
			self.log.error("No releases found!")

		return releases

	def qualifyLink(self, release):

		# have = self.db_sess.query(db.LinkWrappers)                                   \
		# 	.filter(db.LinkWrappers.outbound_wrapper == release['outbound_wrapper']) \
		# 	.filter(db.LinkWrappers.seriesname == release['seriesname'])             \
		# 	.scalar()
		# if have:
		# 	release['actual_target'] = have.actual_target
		# 	self.log.info("Have: %s (%s, %s)", have, release['outbound_wrapper'], release['seriesname'])
		# 	self.amqp.putRow(have)
		# 	return False  # Don't sleep, since we didn't do a remote fetch.

		driver = self.wg.pjs_driver
		basepage = release['referrer']
		if driver.current_url.rstrip("/") != basepage.rstrip("/"):
			self.log.info("Need to resolve '%s' (current URL: '%s')",
					basepage.rstrip("/"),
					driver.current_url.rstrip("/")
				)
			driver.get(basepage)
			time.sleep(random.randint(3, 9))
		selector = "a[href*='" + release['outbound_wrapper'] + "']"
		linkbutton = driver.find_element_by_css_selector(selector)
		if not linkbutton:
			self.log.error("Can't find link to release with selector '%s'", selector)

		linkbutton.click()

		time.sleep(3)

		release['actual_target'] = driver.current_url

		# new = db.LinkWrappers(
		# 	seriesname       = release['seriesname'],
		# 	releaseinfo      = release['releaseinfo'],
		# 	groupinfo        = release['groupinfo'],
		# 	referrer         = release['referrer'],
		# 	outbound_wrapper = release['outbound_wrapper'],
		# 	actual_target    = driver.current_url,
		# 	addtime          = datetime.datetime.now(),
		# 	)

		# self.db_sess.add(new)
		# self.db_sess.commit()
		self.amqp.putRow(release)

		release['actual_target'] = driver.current_url

		self.log.info("New entry!")
		self.log.info("	Series:   '%s'", release['seriesname'])
		self.log.info("	Release:  '%s'", release['releaseinfo'])
		self.log.info("	Group:    '%s'", release['groupinfo'])
		self.log.info("	Outbound: '%s'", release['outbound_wrapper'])
		self.log.info("	Referrer: '%s'", release['referrer'])
		self.log.info("	Real:     '%s'", driver.current_url)

		# driver.execute_script("window.history.go(-1)")
		self.log.info("Attempting to go back to source page")
		for dummy_x in range(5):
			if driver.current_url.rstrip("/") != basepage.rstrip("/"):
				driver.back()
				time.sleep(2)
				self.log.info("	%s -> %s", driver.current_url.rstrip("/"), basepage.rstrip("/"))
		if driver.current_url.rstrip("/") == basepage.rstrip("/"):
			self.log.info("Returned back to base-page.")
		else:
			self.log.error("Could not use back nav control to return to base-page!")

		return True

	def qualifyLinks(self, releaselist):
		limit = random.randint(5, 40)
		random.shuffle(releaselist)
		for release in releaselist:

			# Hash the series name, modulo number of clients,
			# and pick the series that match the active client.
			# This makes each client "picky" about what series
			# it "reads".
			# chp_hash = mmh3.hash(release['seriesname'])
			# chp_hash = chp_hash % self.settings['client_count']
			# if chp_hash != self.settings['client_number']:
			# 	self.log.info("This client doesn't 'want' entries for series '%s'", release['seriesname'])
			# 	continue

			sleep = True
			try:
				sleep = self.qualifyLink(release)
			except selenium.common.exceptions.WebDriverException:
				self.log.error("Error when resolving outbound referrer!")
				for line in traceback.format_exc().split("\n"):
					self.log.error(line)

				raise

			if sleep:

				# Fetch n items per hour max
				limit = limit - 1
				if limit <= 0:
					return

				sleeptime = random.randint(15, 7*60)
				for x in range(sleeptime):
					if x % 15 == 0:
						self.log.info("Sleeping %s seconds (%s remaining)", sleeptime, sleeptime-x)
					time.sleep(1)



	def handlePage(self, url):
		if self.wg == None:
			self.wg = WebRequest.WebGetRobust(cloudflare=True)
		try:
			rawpg = self.fetchPage(url)
			releases = self.processPage(url, rawpg)
			fqreleases = self.qualifyLinks(releases)
		finally:
			try:
				self.log.info("Attempting to shut down PhantomJS")
				self.log.info("PhantomJS instance closed.")
				self.wg.pjs_driver.quit()
			except Exception:
				self.log.error("Issue when shutting down PhantomJS Instance.")
				for line in traceback.format_exc().split("\n"):
					self.log.error(line)
			self.log.info("Dropping WebRequest.")
			self.wg = None

		# print(releases)




def test():
	print("Test mode!")
	import logSetup
	import multiprocessing
	logSetup.initLogging()

	c_lok = cookie_lock = multiprocessing.Lock()
	engine = WebMirror.Engine.SiteArchiver(cookie_lock=c_lok)

	# engine.dispatchRequest(testJobFromUrl('http://www.novelupdates.com/'))

	for x in range(0, 180):
		engine.dispatchRequest(testJobFromUrl('http://www.novelupdates.com/?pg={num}'.format(num=x)))

	# engine.dispatchRequest(testJobFromUrl('http://www.novelupdates.com/?pg=1'))
	# engine.dispatchRequest(testJobFromUrl('http://www.novelupdates.com/?pg=2'))
	# engine.dispatchRequest(testJobFromUrl('http://www.novelupdates.com/?pg=3'))
	# engine.dispatchRequest(testJobFromUrl('http://www.novelupdates.com/?pg=4'))


if __name__ == "__main__":
	print("Testing")
	test()

