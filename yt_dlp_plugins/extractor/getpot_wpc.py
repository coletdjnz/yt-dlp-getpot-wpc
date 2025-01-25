import asyncio
import hashlib
import json
import pathlib
import time
import nodriver
import nodriver.core.config
from yt_dlp import YoutubeDL
from nodriver import start, cdp, loop
from yt_dlp.networking._helper import select_proxy
from yt_dlp.networking.common import Features
from yt_dlp.networking.exceptions import UnsupportedRequest, RequestError
from yt_dlp_plugins.extractor.getpot import GetPOTProvider, register_provider, register_preference


__version__ = '0.1.1'

CACHE_STORE = 'youtube-getpot-wpc'
CACHE_STORE_KEY = 'po_token'
PO_TOKEN_DEFAULT_CACHE_TTL_SECONDS = 12 * 60 * 60  # 12 hours
WEB_PO_BACKOFF_SECONDS = 1


def get_content_binding(client, context, data_sync_id=None, visitor_data=None, video_id=None):
    if context == 'gvs' or client == 'web_music':
        # web_music player or gvs is bound to data_sync_id or visitor_data
        return data_sync_id or visitor_data

    return video_id


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
        raise RequestError('Could not find WebPoClient in browser')

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

    raise RequestError('Timed out waiting for WebPoClient to be ready in browser')


async def launch_browser(config):
    # todo: allow to specify an existing nodriver browser instance
    try:
        browser = await start(config=config)
    except Exception as e:
        raise RequestError(f'failed to start browser: {e}') from e
    await browser.connection.send(cdp.storage.clear_cookies())
    await browser.get('https://www.youtube.com?themeRefresh=1')
    return browser


def build_pot_cache_key(client, context, content_binding):
    hash_str = f'{client}:{context}:{content_binding}'
    return f'{client}:{context}:{hashlib.sha1(hash_str.encode()).hexdigest()}'


@register_provider
class WebPOClientGetPOTRH(GetPOTProvider):
    _PROVIDER_NAME = 'wpc'
    _SUPPORTED_CLIENTS = ('web', 'web_safari', 'web_music', 'web_embedded', 'tv', 'tv_embedded', 'web_creator', 'mweb')
    _SUPPORTED_CONTEXTS = ('gvs', 'player')
    _SUPPORTED_PROXY_SCHEMES = ['http', 'socks4', 'socks5', 'socks4a', 'socks5h']
    _SUPPORTED_FEATURES = [Features.NO_PROXY, Features.ALL_PROXY]
    VERSION = __version__

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._browser = None
        self.__loop = None

    @property
    def _loop(self):
        if not self.__loop:
            self.__loop = loop()
        return self.__loop

    def close(self):
        if self._browser:
            self._loop.run_until_complete(self._browser.close())
            self._browser = None
        super().close()

    def _cache_token(self, ie, po_token, expires_at, client, context, content_binding):
        token_data = {
            'po_token': po_token,
            'expires_at': expires_at
        }

        cached_tokens = self._get_cached_tokens(ie)
        cached_tokens[build_pot_cache_key(client, context, content_binding)] = token_data

        # clear any tokens that have expired
        active_cached_tokens = {k: v for k, v in cached_tokens.items() if v['expires_at'] > time.time()}

        ie.cache.store(CACHE_STORE, CACHE_STORE_KEY, active_cached_tokens)

    def _get_cached_tokens(self, ie):
        return ie.cache.load(CACHE_STORE, CACHE_STORE_KEY) or {}

    def _get_cached_token(self, ie, context, client, content_binding):
        key = build_pot_cache_key(client, context, content_binding)
        token_data = self._get_cached_tokens(ie).get(key)

        if not token_data:
            return None

        if token_data['expires_at'] < time.time():
            self._logger.debug(f'Cached {context} PO Token expired')
            return None

        return token_data['po_token']

    def get_config_setting(self, ie, key, casesense=True, default=None):
        return ie._configuration_arg(key, [default], ie_key=f'youtube-{self._PROVIDER_NAME}', casesense=casesense)[0]

    def get_nodriver_config(self, ie, proxy=None):
        browser_executable_path = self.get_config_setting(ie, 'browser_path', default=None)
        browser_args = []
        if proxy:
            # xxx: potentially unsafe
            browser_args.extend([f'--proxy-server={proxy}'])

        return nodriver.core.config.Config(
            headless=False,
            browser_executable_path=browser_executable_path,
            browser_args=browser_args
        )

    def _validate_get_pot(
            self,
            client: str,
            ydl: YoutubeDL,
            context=None,
            **kwargs
    ):
        ie = ydl.get_info_extractor('Youtube')
        mint_player_tokens = True if self.get_config_setting(ie, 'mint_player_tokens', default='True') == 'True' else False
        if context == 'player' and not mint_player_tokens:
            raise UnsupportedRequest('Player PO Token minting is disabled')

        # check that chrome is available
        nodriver_config = self.get_nodriver_config(ie)
        if not nodriver_config.browser_executable_path or not pathlib.Path(nodriver_config.browser_executable_path).exists():
            self._logger.warning(
                'wpc provider requires Chrome to be installed. '
                'You can specify a path to the browser with --extractor-args "youtube-wpc:browser_path=XYZ".',
                once=True)
            raise UnsupportedRequest('WebPoClient requires Chrome to be installed')

    def _get_pot(self, client: str, ydl: YoutubeDL, visitor_data=None, data_sync_id=None, video_id=None, context=None, **kwargs) -> str:
        ie = ydl.get_info_extractor('Youtube')
        enable_cache = True if self.get_config_setting(ie, 'cache', default='True') == 'True' else False
        cache_ttl = int(self.get_config_setting(ie, 'cache_ttl', default=PO_TOKEN_DEFAULT_CACHE_TTL_SECONDS))

        content_binding = get_content_binding(client, context, data_sync_id, visitor_data, video_id)
        proxy = select_proxy('https://www.youtube.com', self.proxies)
        if proxy:
            proxy = proxy.replace('socks5h', 'socks5').replace('socks4a', 'socks4')

        browser_config = self.get_nodriver_config(ie, proxy)

        cache_content_binding = content_binding + (proxy or '')

        if enable_cache:
            po_token = self._get_cached_token(ie, context, client, cache_content_binding)
            if po_token:
                self._logger.debug(f'Retrieved {context} PO Token from cache: {po_token}')
                return po_token

        if not self._browser or self._browser.stopped:
            self._logger.info(f'Launching youtube.com in browser to retrieve PO Token(s). '
                              f'This will stay open while yt-dlp is running. Do not close the browser window!')
            self._browser = self._loop.run_until_complete(launch_browser(browser_config))

        self._logger.debug(f"Minting {context} PO Token using WebPoClient in browser")
        po_token = self._loop.run_until_complete(
            mint_po_token(tab=self._browser.main_tab, logger=self._logger, content_binding=content_binding))

        if enable_cache:
            self._cache_token(ie, po_token, int(time.time()) + cache_ttl, client, context, cache_content_binding)
        self._logger.debug(f'Retrieved {context} PO Token: {po_token}')
        return po_token


@register_preference(WebPOClientGetPOTRH)
def wpc_preference(rh, request):
    return -100
