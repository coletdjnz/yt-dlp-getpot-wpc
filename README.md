# WebPoClient PO Token Provider

An experimental yt-dlp [PO Token Provider](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide#po-token-provider-plugins) that uses [nodriver](https://github.com/ultrafunkamsterdam/nodriver) and YouTube's "WebPoClient" in the browser mint PO Tokens.

Supports:
- WebPO-based clients (`web`, `web_safari`, `web_music`, `mweb` `tv`, `tv_embedded`, `web_embedded`, `web_creator`, ...)
- Minting GVS and Player PO Tokens
- Minting PO Tokens for both guest and logged-in sessions

<!-- TOC -->
* [WebPoClient PO Token Provider](#webpoclient-po-token-provider)
  * [Installing](#installing)
    * [pip/pipx](#pippipx)
  * [Usage](#usage)
    * [Options](#options)
      * [Custom Chrome Location](#custom-chrome-location)
<!-- TOC -->

## Installing

**Requires yt-dlp `2025.09.26` or above.**

Chrome or Chromium must be installed.

### pip/pipx

```
pipx inject yt-dlp yt-dlp-getpot-wpc
```

or

```
python3 -m pip install -U yt-dlp-getpot-wpc
```


If installed correctly, you should see the `wpc` PO Token provider in `yt-dlp -v YOUTUBE_URL` output

    [debug] [youtube] [pot] PO Token Providers: wpc-1.x.y (external)


## Usage

This provider will automatically be used when a PO Token is requested by yt-dlp. It will launch a web browser while yt-dlp is running which it will use to mint PO Token(s).

> [!WARNING]
> Do not close the browser that is launched when yt-dlp is running!

### Options


#### Custom Chrome Location

Set the location of the Chrome browser executable to use.

`--extractor-args "youtubepot-wpc:browser_path=/usr/bin/chromium"`