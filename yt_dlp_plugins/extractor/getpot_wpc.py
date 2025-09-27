import asyncio
import functools
import pathlib
import nodriver
import nodriver.core.config
from nodriver import start, cdp, loop

from yt_dlp.extractor.youtube.pot.provider import (
    PoTokenRequest,
    PoTokenContext,
    PoTokenProvider,
    PoTokenResponse,
    PoTokenProviderError,
    register_provider,
    register_preference,
    ExternalRequestFeature, provider_bug_report_message,
)
from yt_dlp.extractor.youtube.pot.utils import get_webpo_content_binding, WEBPO_CLIENTS
import json


__version__ = '1.0.0'

WEB_PO_BACKOFF_SECONDS = 1

async def get_webpo_client_path(tab, logger):
    # todo: dynamically extract
    # note: this assumes "bg_st_hr" experiment is enabled
    webpo_client_path = "window.top['havuokmhhs-0']?.bevasrs?.wpc"

    count = 0
    while count < 10 and not await tab.evaluate(f"!!{webpo_client_path}"):
        logger.debug('Waiting for WebPoClient to be available in browser...')
        # check that ytcfg is loaded and bg_st_hr experiment is enabled
        if not await tab.evaluate(
            f"!window.top['ytcfg']?.get('EXPERIMENT_FLAGS') || !!ytcfg.get('EXPERIMENT_FLAGS')?.bg_st_hr"
        ):
            logger.warning(
                'bg_st_hr experiment is not enabled, WebPoClient may not be available.', once=True)

        await asyncio.sleep(WEB_PO_BACKOFF_SECONDS)
        count += 1

    if count == 10:
        logger.error('Timed out waiting for WebPoClient to be available in browser')
        return False

    return webpo_client_path


async def mint_po_token(tab, logger, content_binding, mint_cold_start_token=False, mint_error_token=False):
    webpo_client_path = await get_webpo_client_path(tab, logger)
    if not webpo_client_path:
        raise PoTokenProviderError('Could not find WebPoClient in browser')

    mws_params = {
        'c': content_binding,
        'mc': mint_cold_start_token,
        'me': mint_error_token
    }

    mint_po_token_code = f"""
        {webpo_client_path}().then((client) => client.mws({json.dumps(mws_params)})).catch(
            (e) => {{
                if (String(e).includes('SDF:notready')) {{
                    return 'backoff';
                }}
                else {{
                    throw e;
                }}
            }}
        )
        """

    tries = 0
    while tries < 10:
        po_token = await tab.evaluate(mint_po_token_code, await_promise=True)
        if po_token != 'backoff':
            return po_token
        logger.debug('Waiting for WebPoClient to be ready in browser...')
        await asyncio.sleep(WEB_PO_BACKOFF_SECONDS)
        tries += 1

    raise PoTokenProviderError('Timed out waiting for WebPoClient to be ready in browser')


async def launch_browser(config):
    # todo: allow to specify an existing nodriver browser instance
    try:
        browser = await start(config=config)
    except Exception as e:
        raise PoTokenProviderError(f'failed to start browser: {e}') from e
    await browser.connection.send(cdp.storage.clear_cookies())
    await browser.get('https://www.youtube.com?themeRefresh=1')
    return browser

@register_provider
class WPCPTP(PoTokenProvider):
    PROVIDER_VERSION = __version__
    # Define a unique display name for the provider
    PROVIDER_NAME = 'wpc'
    BUG_REPORT_LOCATION = 'https://github.com/coletdjnz/yt-dlp-getpot-wpc/issues'

    _SUPPORTED_CLIENTS = WEBPO_CLIENTS

    _SUPPORTED_CONTEXTS = (
        PoTokenContext.GVS,
        PoTokenContext.PLAYER,
        PoTokenContext.SUBS,
    )

    _SUPPORTED_EXTERNAL_REQUEST_FEATURES = (
        ExternalRequestFeature.PROXY_SCHEME_HTTP,
        ExternalRequestFeature.PROXY_SCHEME_SOCKS4,
        ExternalRequestFeature.PROXY_SCHEME_SOCKS4A,
        ExternalRequestFeature.PROXY_SCHEME_SOCKS5,
        ExternalRequestFeature.PROXY_SCHEME_SOCKS5H,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._browser = None
        self.__loop = None
        self._available = False

    @property
    def _loop(self):
        if not self.__loop:
            self.__loop = loop()
        return self.__loop

    def close(self):
        if self._browser:
            self._browser.stop()
            self._browser = None
        super().close()

    def get_nodriver_config(self, proxy=None):
        browser_executable_path = (
            self._configuration_arg('browser_path', casesense=True, default=[None])[0]
            # backwards-compat
            or self.ie._configuration_arg('browser_path', [None], ie_key=f'youtube-wpc', casesense=True)[0]
        )
        browser_args = []
        if proxy:
            # xxx: potentially unsafe
            browser_args.extend([f'--proxy-server={proxy}'])

        return nodriver.core.config.Config(
            headless=False,
            browser_executable_path=browser_executable_path,
            browser_args=browser_args
        )

    @functools.cache
    def is_available(self):
        # check that chrome is available
        missing_browser = False
        nodriver_config = None
        try:
            nodriver_config = self.get_nodriver_config()
        except FileNotFoundError as e:
            if 'chrome' in str(e):
                missing_browser = True
            else:
                self.logger.warning(f'Unexpected error while getting browser config: {e}{provider_bug_report_message(self)}')
                return False
        if (
            missing_browser
            or not nodriver_config.browser_executable_path
            or not pathlib.Path(nodriver_config.browser_executable_path).exists()
        ):
            self.logger.debug(
                'WPC PO Token Provider requires Chrome to be installed. '
                'You can specify a path to the browser with --extractor-args "youtubepot-wpc:browser_path=XYZ".')
            return False

        return True

    def _real_request_pot(self, request: PoTokenRequest) -> PoTokenResponse:
        proxy = request.request_proxy
        if proxy:
            proxy = proxy.replace('socks5h', 'socks5').replace('socks4a', 'socks4')

        browser_config = self.get_nodriver_config(proxy)
        if not self._browser or self._browser.stopped:
            self.logger.info(f'Launching youtube.com in browser to retrieve PO Token(s). '
                              f'This will stay open while yt-dlp is running. Do not close the browser window!')
            self._browser = self._loop.run_until_complete(launch_browser(browser_config))

        self.logger.info(f"Minting {request.context.value} PO Token for {request.internal_client_name} using WebPoClient in browser")
        po_token = self._loop.run_until_complete(
            mint_po_token(tab=self._browser.main_tab, logger=self.logger, content_binding=get_webpo_content_binding(request)[0]))

        self.logger.trace(f'Retrieved {request.context.value} PO Token: {po_token}')
        return PoTokenResponse(po_token=po_token)


@register_preference(WPCPTP)
def wpc_preference(_, __):
    return -100
