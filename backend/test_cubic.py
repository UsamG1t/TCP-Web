"""Verify the CUBIC implementation against the formulas in RFC 9438.

Runs the strategy against a stand-in engine rather than the real one, so each
rule can be checked in isolation with hand-picked state: the multiplicative
decrease of Sec. 4.6, the timeout rules of 4.8, the value of K from 4.2 and
4.10, and the shape of the window curve through the concave and convex regions.

Not a pytest suite — a script. Run it directly from the backend directory:

    python3 test_cubic.py

It raises AssertionError on the first rule that does not match the standard, and
prints the observed curve so the concave-to-convex transition can be eyeballed.
"""
import sys; sys.path.insert(0,'.')
from engine.congestion import Cubic, C_CUBIC, BETA_CUBIC, ALPHA_CUBIC

class FakeEngine:
    """Minimal stand-in exposing only what a strategy touches.

    Records every window change so assertions can inspect the sequence, and
    reports fixed values for the smoothed RTT and flight size so each rule can
    be tested against known inputs.
    """

    def __init__(self, cwnd=100.0, srtt_ms=100.0, flight=None):
        self.cwnd=cwnd; self.ssthresh=1e9; self.phase="congestion-avoidance"
        self.now=0.0; self._srtt=srtt_ms; self._flight=flight if flight else int(cwnd)
        self.cubic={"wmax":0.0,"t_epoch":0.0,"cwnd_epoch":0.0,"cwnd_prior":0.0,
                    "w_est":0.0,"k":0.0,"epoch_started":False,"after_congestion":False}
        self.events=[]
    def set_cwnd(self,v,reason=""):
        """Apply a window change and record it for inspection."""
        self.cwnd=max(1.0,v); self.events.append((self.now,self.cwnd,reason))

    def set_phase(self,p):
        """Record the sender phase."""
        self.phase=p

    def emit_ssthresh(self):
        """Ignore threshold events; the tests read `ssthresh` directly."""
        pass

    def fast_retransmit(self):
        """Ignore retransmission; the tests only check window policy."""
        pass

    def srtt_s(self):
        """Return the fixed smoothed RTT in seconds."""
        return self._srtt/1000.0

    def flight_size(self):
        """Return the fixed number of outstanding segments."""
        return self._flight

cc=Cubic()
print("ALPHA_CUBIC = %.4f  (RFC: 3*(1-0.7)/(1+0.7) = %.4f)" % (ALPHA_CUBIC, 3*0.3/1.7))
assert abs(ALPHA_CUBIC - 3*0.3/1.7) < 1e-12

# --- 1. Multiplicative decrease uses flight_size * beta (§4.6) ---
e=FakeEngine(cwnd=100.0, flight=80)
cc.on_triple_dup_ack(e)
print("\n[4.6] MD: flight=80 -> ssthresh=%.1f (expect 80*0.7=56.0), cwnd=%.1f (expect 70.0), cwnd_prior=%.0f"
      % (e.ssthresh, e.cwnd, e.cubic["cwnd_prior"]))
assert abs(e.ssthresh-56.0)<1e-9 and abs(e.cwnd-70.0)<1e-9 and e.cubic["cwnd_prior"]==100.0

# --- 2. Timeout: ssthresh via beta (NOT 1/2), cwnd=1, K=0 next CA (§4.8) ---
e=FakeEngine(cwnd=100.0, flight=90)
cc.on_timeout(e)
print("[4.8] RTO: ssthresh=%.1f (expect 90*0.7=63.0, NOT 50), cwnd=%.1f, phase=%s, after_congestion=%s"
      % (e.ssthresh, e.cwnd, e.phase, e.cubic["after_congestion"]))
assert abs(e.ssthresh-63.0)<1e-9 and e.cwnd==1.0 and e.cubic["after_congestion"] is False

# --- 3. K after a congestion event (§4.2) ---
e=FakeEngine(cwnd=70.0); e.cubic["cwnd_prior"]=100.0; e.cubic["after_congestion"]=True
cc._start_epoch(e)
k_expected=((100.0-70.0)/C_CUBIC)**(1/3)
print("[4.2] K after loss: got %.4f, expect cbrt((Wmax-cwnd_epoch)/C)=cbrt(30/0.4)=%.4f | Wmax=%.0f W_est=%.0f"
      % (e.cubic["k"], k_expected, e.cubic["wmax"], e.cubic["w_est"]))
assert abs(e.cubic["k"]-k_expected)<1e-9 and e.cubic["wmax"]==100.0 and e.cubic["w_est"]==70.0

# --- 4. K = 0 on CA entry from slow start (§4.10 / §4.8) ---
e=FakeEngine(cwnd=40.0); e.cubic["after_congestion"]=False
cc._start_epoch(e)
print("[4.10] K on slow-start exit: %.1f (expect 0.0), Wmax=%.0f (expect cwnd=40), cwnd_prior=%.0f"
      % (e.cubic["k"], e.cubic["wmax"], e.cubic["cwnd_prior"]))
assert e.cubic["k"]==0.0 and e.cubic["wmax"]==40.0 and e.cubic["cwnd_prior"]==40.0

# --- 5. Curve shape: cwnd should track W_cubic and plateau near Wmax at t≈K ---
print("\n[4.2/4.4/4.5] форма кривой после потери (Wmax=100, cwnd_epoch=70):")
e=FakeEngine(cwnd=70.0, srtt_ms=100.0); e.cubic["cwnd_prior"]=100.0; e.cubic["after_congestion"]=True
K=None
for step in range(4000):
    e.now = step*10.0                      # 10 ms per ACK
    cc.on_new_ack(e, acked=step, segments_acked=1)
    if K is None: K=e.cubic["k"]
    t=(e.now-e.cubic["t_epoch"])/1000.0
    if step % 400 == 0:
        w_theory = C_CUBIC*(t-K)**3 + 100.0
        region = "concave" if e.cwnd < e.cubic["wmax"] else "convex"
        print("   t=%5.1fs (K=%.2f) cwnd=%7.2f   W_cubic(t)=%7.2f   %s" % (t,K,e.cwnd,w_theory,region))
print("   -> при t≈K (%.2fs) окно должно быть ≈Wmax=100" % K)
