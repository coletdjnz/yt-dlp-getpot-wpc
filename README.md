# WebPOClient PO Token Provider

An experimental [GetPOT](https://github.com/coletdjnz/yt-dlp-get-pot) PO Token Provider for yt-dlp that uses [nodriver](https://github.com/ultrafunkamsterdam/nodriver) to mint PO Tokens using YouTube's webPoClient in the web browser.

Supports:
- yt-dlp WebPO-based clients (`web`, `web_safari`,  `web_music`, `mweb` `tv`, `tv_embedded`, `web_embedded`, `web_creator`)
- Minting GVS and Player PO Tokens
- Minting PO Tokens for both guest and logged-in sessions

<!-- TOC -->
* [WebPOClient PO Token Provider](#webpoclient-po-token-provider)
  * [Installing](#installing)
    * [pip/pipx](#pippipx)
  * [Usage](#usage)
    * [Options](#options)
      * [Toggle caching](#toggle-caching)
      * [Set cache TTL](#set-cache-ttl)
      * [Mint Player Tokens](#mint-player-tokens)
<!-- TOC -->

## Installing

**Requires yt-dlp `2025.01.15` or above.**

### pip/pipx

```
pipx inject yt-dlp yt-dlp-getpot-wpc
```
or

```
python3 -m pip install -U yt-dlp-getpot-wpc
```


If installed correctly, you should see the `wpc` PO Token provider in `yt-dlp -v YOUTUBE_URL` output

    [debug] [GetPOT] PO Token Providers: wpc


## Usage

This provider will automatically be used when a PO Token is requested by yt-dlp. It will launch a web browser while yt-dlp is running which it will use to mint PO Token(s).

> [!WARNING]
> Do not close the browser that is launched when yt-dlp is running!

### Options

> [!CAUTION]
> These options may change without warning

#### Toggle caching

Toggle caching of PO Tokens generated. This uses the yt-dlp cache (`--cache-dir`) to store PO Tokens. Default is `True`.

`--extractor-args "youtube-wpc:cache=False"`

#### Set cache TTL

Set the cache TTL in seconds. Default is 12 hours.

`--extractor-args "youtube-wpc:cache_ttl=3600"`


#### Mint Player Tokens

Toggle minting of Player Tokens. Default is `True`.

`--extractor-args "youtube-wpc:mint_player=False"`
