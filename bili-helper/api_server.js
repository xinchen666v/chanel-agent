// ==UserScript==
// @name         追番进度小助手 (事件驱动版)
// @namespace    http://tampermonkey.net/
// @version      0.8
// @description  播放、暂停、结束、关闭时上报进度，每60秒更新一次进度
// @match        https://www.bilibili.com/video/*
// @match        https://www.bilibili.com/bangumi/play/*
// @run-at       document-idle
// @grant        GM_xmlhttpRequest
// ==/UserScript==

(function() {
    'use strict';
    const API_URL = 'http://localhost:3000/update';
    let lastReportedProgress = '-1%';

    function getData() {
        const bvid = window.location.pathname.match(/\/video\/(BV\w+)/)?.[1] || '';
        let title = document.querySelector('meta[property="og:title"]')?.getAttribute('content') ||
                    document.querySelector('h1.video-title')?.textContent?.trim() ||
                    '未知标题';
        const video = document.querySelector('video');
        let progress = '0%', currentTime = 0, duration = 1;
        if (video && video.duration) {
            currentTime = video.currentTime || 0;
            duration = video.duration || 1;
            progress = Math.round((currentTime / duration) * 100) + '%';
        }
        return { bvid, title, progress, currentTime, duration, timestamp: new Date().toISOString() };
    }

    function reportProgress(isPageUnloading = false) {
        const data = getData();
        if (!data.bvid) return;
        if (data.progress === lastReportedProgress) return;
        lastReportedProgress = data.progress;

        console.log(`📤 上报进度: ${data.progress} (${isPageUnloading ? '页面关闭' : '事件触发'})`);

        if (isPageUnloading) {
            // 页面关闭时用 sendBeacon（不能被取消）
            navigator.sendBeacon(API_URL, new Blob([JSON.stringify(data)], {type: 'application/json'}));
        } else {
            // 正常场景用 GM_xmlhttpRequest
            GM_xmlhttpRequest({
                method: 'POST',
                url: API_URL,
                headers: { 'Content-Type': 'application/json' },
                data: JSON.stringify(data),
                onload: () => console.log('✅ 上报成功:', data.progress),
                onerror: (e) => console.error('❌ 上报失败:', e)
            });
        }
    }

    function setupListeners() {
        const video = document.querySelector('video');
        if (!video) {
            console.warn('⏳ 等待 video 元素加载...');
            setTimeout(setupListeners, 1000);
            return;
        }

        // 1. 开始播放时上报（核心：让 DB 立即知道在播什么）
        video.addEventListener('play', () => reportProgress(false));

        // 2. 播放中每 60 秒更新一次进度（长时间观看不丢失进度）
        video.addEventListener('timeupdate', () => {
            if (video.paused) return;
            const now = Date.now();
            if (!video._lastTimeupdate || now - video._lastTimeupdate > 60000) {
                video._lastTimeupdate = now;
                reportProgress(false);
            }
        });

        // 3. 暂停时上报
        video.addEventListener('pause', () => reportProgress(false));

        // 4. 播放完毕时上报
        video.addEventListener('ended', () => reportProgress(false));

        // 5. 页面关闭/刷新时上报（核心）
        window.addEventListener('pagehide', () => reportProgress(true));

        console.log('🎬 追番小助手 v0.8 已就绪，等待播放事件...');
    }

    setupListeners();
})();