from migen.fhdl.std import *
from migen.genlib.cdc import MultiReg, PulseSynchronizer
from migen.bank.description import *

class DataCapture(Module, AutoCSR):
	def __init__(self, pad_p, pad_n, ntbits):
		self.serdesstrobe = Signal()
		self.d = Signal(10)

		self._r_dly_ctl = CSR(6)
		self._r_dly_busy = CSRStatus(2)
		self._r_phase = CSRStatus(2)
		self._r_phase_reset = CSR()

		###

		# IO
		pad_se = Signal()
		self.specials += Instance("IBUFDS", i_I=pad_p, i_IB=pad_n, o_O=pad_se)

		pad_delayed_master = Signal()
		pad_delayed_slave = Signal()
		delay_inc = Signal()
		delay_ce = Signal()
		delay_master_cal = Signal()
		delay_master_rst = Signal()
		delay_master_busy = Signal()
		delay_slave_cal = Signal()
		delay_slave_rst = Signal()
		delay_slave_busy = Signal()
		self.specials += Instance("IODELAY2",
			p_SERDES_MODE="MASTER",
			p_DELAY_SRC="IDATAIN", p_IDELAY_TYPE="DIFF_PHASE_DETECTOR",
			p_COUNTER_WRAPAROUND="STAY_AT_LIMIT", p_DATA_RATE="SDR",

			i_IDATAIN=pad_se, o_DATAOUT=pad_delayed_master,
			i_CLK=ClockSignal("pix5x"), i_IOCLK0=ClockSignal("pix10x"),

			i_INC=delay_inc, i_CE=delay_ce,
			i_CAL=delay_master_cal, i_RST=delay_master_rst, o_BUSY=delay_master_busy,
			i_T=1)
		self.specials += Instance("IODELAY2",
			p_SERDES_MODE="SLAVE",
			p_DELAY_SRC="IDATAIN", p_IDELAY_TYPE="DIFF_PHASE_DETECTOR",
			p_COUNTER_WRAPAROUND="STAY_AT_LIMIT", p_DATA_RATE="SDR",

			i_IDATAIN=pad_se, o_DATAOUT=pad_delayed_slave,
			i_CLK=ClockSignal("pix5x"), i_IOCLK0=ClockSignal("pix10x"),

			i_INC=delay_inc, i_CE=delay_ce,
			i_CAL=delay_slave_cal, i_RST=delay_slave_rst, o_BUSY=delay_slave_busy,
			i_T=1)

		d0 = Signal()
		d1 = Signal()
		pd_valid = Signal()
		pd_incdec = Signal()
		pd_edge = Signal()
		pd_cascade = Signal()
		self.specials += Instance("ISERDES2",
			p_SERDES_MODE="MASTER",
			p_BITSLIP_ENABLE="FALSE", p_DATA_RATE="SDR", p_DATA_WIDTH=2,
			p_INTERFACE_TYPE="RETIMED",

			i_D=pad_delayed_master,
			o_Q4=d0, o_Q3=d1,

			i_BITSLIP=0, i_CE0=1, i_RST=0,
			i_CLK0=ClockSignal("pix10x"), i_CLKDIV=ClockSignal("pix5x"),
			i_IOCE=self.serdesstrobe,

			o_VALID=pd_valid, o_INCDEC=pd_incdec,
			i_SHIFTIN=pd_edge, o_SHIFTOUT=pd_cascade)
		self.specials += Instance("ISERDES2",
			p_SERDES_MODE="SLAVE",
			p_BITSLIP_ENABLE="FALSE", p_DATA_RATE="SDR", p_DATA_WIDTH=2,
			p_INTERFACE_TYPE="RETIMED",

			i_D=pad_delayed_slave,

			i_BITSLIP=0, i_CE0=1, i_RST=0,
			i_CLK0=ClockSignal("pix10x"), i_CLKDIV=ClockSignal("pix5x"),
			i_IOCE=self.serdesstrobe,

			i_SHIFTIN=pd_cascade, o_SHIFTOUT=pd_edge)

		# Phase error accumulator
		lateness = Signal(ntbits, reset=2**(ntbits - 1))
		too_late = Signal()
		too_early = Signal()
		reset_lateness = Signal()
		self.comb += [
			too_late.eq(lateness == (2**ntbits - 1)),
			too_early.eq(lateness == 0)
		]
		self.sync.pix5x += [
			If(reset_lateness,
				lateness.eq(2**(ntbits - 1))
			).Elif(~delay_master_busy & ~delay_slave_busy & ~too_late & ~too_early,
				If(pd_valid &  pd_incdec, lateness.eq(lateness - 1)),
				If(pd_valid & ~pd_incdec, lateness.eq(lateness + 1))
			)
		]

		# Delay control
		self.submodules.delay_master_done = PulseSynchronizer("pix5x", "sys")
		delay_master_pending = Signal()
		self.sync.pix5x += [
			self.delay_master_done.i.eq(0),
			If(~delay_master_pending,
				If(delay_master_cal | delay_ce, delay_master_pending.eq(1))
			).Else(
				If(~delay_master_busy,
					self.delay_master_done.i.eq(1),
					delay_master_pending.eq(0)
				)
			)
		]
		self.submodules.delay_slave_done = PulseSynchronizer("pix5x", "sys")
		delay_slave_pending = Signal()
		self.sync.pix5x += [
			self.delay_slave_done.i.eq(0),
			If(~delay_slave_pending,
				If(delay_slave_cal | delay_ce, delay_slave_pending.eq(1))
			).Else(
				If(~delay_slave_busy,
					self.delay_slave_done.i.eq(1),
					delay_slave_pending.eq(0)
				)
			)
		]

		self.submodules.do_delay_master_cal = PulseSynchronizer("sys", "pix5x")
		self.submodules.do_delay_master_rst = PulseSynchronizer("sys", "pix5x")
		self.submodules.do_delay_slave_cal = PulseSynchronizer("sys", "pix5x")
		self.submodules.do_delay_slave_rst = PulseSynchronizer("sys", "pix5x")
		self.submodules.do_delay_inc = PulseSynchronizer("sys", "pix5x")
		self.submodules.do_delay_dec = PulseSynchronizer("sys", "pix5x")
		self.comb += [
			delay_master_cal.eq(self.do_delay_master_cal.o),
			delay_master_rst.eq(self.do_delay_master_rst.o),
			delay_slave_cal.eq(self.do_delay_slave_cal.o),
			delay_slave_rst.eq(self.do_delay_slave_rst.o),
			delay_inc.eq(self.do_delay_inc.o),
			delay_ce.eq(self.do_delay_inc.o | self.do_delay_dec.o),
		]

		sys_delay_master_pending = Signal()
		self.sync += [
			If(self.do_delay_master_cal.i | self.do_delay_inc.i | self.do_delay_dec.i,
				sys_delay_master_pending.eq(1)
			).Elif(self.delay_master_done.o,
				sys_delay_master_pending.eq(0)
			)
		]
		sys_delay_slave_pending = Signal()
		self.sync += [
			If(self.do_delay_slave_cal.i | self.do_delay_inc.i | self.do_delay_dec.i,
				sys_delay_slave_pending.eq(1)
			).Elif(self.delay_slave_done.o,
				sys_delay_slave_pending.eq(0)
			)
		]

		self.comb += [
			self.do_delay_master_cal.i.eq(self._r_dly_ctl.re & self._r_dly_ctl.r[0]),
			self.do_delay_master_rst.i.eq(self._r_dly_ctl.re & self._r_dly_ctl.r[1]),
			self.do_delay_slave_cal.i.eq(self._r_dly_ctl.re & self._r_dly_ctl.r[2]),
			self.do_delay_slave_rst.i.eq(self._r_dly_ctl.re & self._r_dly_ctl.r[3]),
			self.do_delay_inc.i.eq(self._r_dly_ctl.re & self._r_dly_ctl.r[4]),
			self.do_delay_dec.i.eq(self._r_dly_ctl.re & self._r_dly_ctl.r[5]),
			self._r_dly_busy.status.eq(Cat(sys_delay_master_pending, sys_delay_slave_pending))
		]

		# Phase detector control
		self.specials += MultiReg(Cat(too_late, too_early), self._r_phase.status)
		self.submodules.do_reset_lateness = PulseSynchronizer("sys", "pix5x")
		self.comb += [
			reset_lateness.eq(self.do_reset_lateness.o),
			self.do_reset_lateness.i.eq(self._r_phase_reset.re)
		]

		# 2:10 deserialization
		dsr = Signal(10)
		self.sync.pix5x += dsr.eq(Cat(dsr[2:], d1, d0))
		self.sync.pix += self.d.eq(dsr)
