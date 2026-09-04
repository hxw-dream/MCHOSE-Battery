(function () {
  if (window.__kbpatched) return; window.__kbpatched = 1;
  const H = window.HIDDevice;
  if (!H) { console.log('[KB-no-HIDDevice-in-this-realm]'); return; }
  const hex = (d) => { try { return JSON.stringify(Array.from(new Uint8Array(d.buffer || d))); } catch (e) { return 'ERR'; } };
  const oSR = H.sendReport, oSFR = H.sendFeatureReport, oRFR = H.receiveFeatureReport, oOpen = H.open;
  H.sendReport = function (rid, data) {
    console.log('[KB-sendReport] rid=' + rid + ' len=' + (data ? data.length : -1) + ' ' + hex(data));
    return oSR.apply(this, arguments);
  };
  H.sendFeatureReport = function (rid, data) {
    console.log('[KB-sendFeatureReport] rid=' + rid + ' ' + hex(data));
    return oSFR.apply(this, arguments);
  };
  H.receiveFeatureReport = function (rid) {
    const p = oRFR.apply(this, arguments);
    if (p && p.then) return p.then(buf => { console.log('[KB-recvFeatureReport] rid=' + rid + ' ' + hex(buf)); return buf; });
    return p;
  };
  H.open = async function () {
    const info = this.productName + ' vid=' + this.vendorId + ' pid=' + this.productId;
    const r = await oOpen.apply(this, arguments);
    console.log('[KB-open] ' + info);
    try {
      this.addEventListener('inputreport', e => console.log('[KB-IN] rid=' + e.reportId + ' ' + hex(e.data)));
    } catch (e) {}
    return r;
  };
  console.log('[KB-patch-installed]');
})();
