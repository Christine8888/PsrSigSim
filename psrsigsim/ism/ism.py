from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
import numpy as np
from scipy import stats
import sys, time
from ..utils.utils import make_quant, shift_t
from ..utils.constants import DM_K
from ..utils.constants import KOLMOGOROV_BETA

class ISM(object):
    '''
    Class for modeling interstellar medium effects on pulsar signals.
    '''
    def __init__(self):
        ''''''
        pass

    def disperse(self, signal, dm):
        """
        Function to calculate the dispersion
        per frequency bin for 1/f^2 dispersion
        """
        signal._dm = make_quant(dm,'pc/cm^3')

        if hasattr(signal,'_dispersed'):
            raise ValueError('Signal has already been dispersed!')

        if signal.sigtype=='FilterBankSignal':
            self._disperse_filterbank(signal, signal._dm)
        elif signal.sigtype=='BasebandSignal':
            self._disperse_baseband(signal, signal._dm)

        signal._dispersed = True

    def _disperse_filterbank(self, signal, dm):
        #freq in MHz, delays in milliseconds
        freq_array = signal._dat_freq
        time_delays = (DM_K * dm * np.power(freq_array,-2)).to('ms')
        #Dispersion as compared to infinite frequency
        shift_dt = (1/signal._samprate).to('ms')
        shift_start = time.time()

        for ii, freq in enumerate(freq_array):
            signal._data[ii,:] = shift_t(signal._data[ii,:],
                                         time_delays[ii].value,
                                         dt=shift_dt.value)
            if (ii+1) % int(signal.Nchan//20) ==0:
                shift_check = time.time()
                percent = round((ii + 1)*100/signal.Nchan)
                elapsed = shift_check-shift_start
                chk_str = '\r{0:2.0f}% dispersed'.format(percent)
                chk_str += ' in {0:4.3f} seconds.'.format(elapsed)

                try:
                    print(chk_str , end='', flush=True)
                #This is the Python 2 version
                #__future__ does not have 'flush' kwarg.
                except:
                    print(chk_str , end='')
                sys.stdout.flush()

    def _disperse_baseband(self, signal, dm):
        """
        Broadens & delays baseband signal w transfer function defined in PSR
        Handbook, D. Lorimer and M. Kramer, 2006
        Returns a baseband signal dispersed by the ISM.
        Use plot_dispersed() in PSS_plot.py to see the
        dispersed and undispersed signal.
        """
        for x in range(signal.Nchan):
            sig = signal._data[x]
            f0 = signal._fcent
            dt = (1/signal._samprate).to('us')

            fourier = np.fft.rfft(sig)
            u = make_quant(np.fft.rfftfreq(2 * len(fourier) - 1,
                                d=dt.to('s').value), 'us')
            f = u-signal.bw/2. # u in [0,bw], f in [-bw/2, bw/2]

            # Lorimer & Kramer 2006, eqn. 5.21
            H = np.exp(1j*2*np.pi*DM_K/((f+f0)*f0**2)*dm*f**2)

            product = fourier*H
            Dispersed = np.fft.irfft(product)

            if self.MD.mode == 'explore':
                self.Signal_in.undispersedsig[x] = sig
            signal._data[x] = Dispersed
    
    def FD_shift(self, signal, FD_params):
        """
        This calculates the delay that will be added due to an arbitrary number 
        of input FD parameters following the NANOGrav standard as defined in 
        Arzoumanian et al. 2016. It will then shift the pulse profiles by the 
        appropriate amount based on these parameters.
        
        FD values should be input in units of seconds, frequency array in MHz
        FD values can be a list or an array
        """
        #freq in MHz, delays in milliseconds
        freq_array = signal._dat_freq
        # define the reference frequency
        ref_freq = make_quant(1000.0, 'MHz')
        # calculate the delay added in for the parameters
        time_delays = make_quant(np.zeros(len(freq_array)), 'ms') # will be in seconds
        for ii in range(len(FD_params)):
            time_delays += np.double(-1.0*make_quant(FD_params[ii], 's').to('ms') * \
                    np.power(np.log(freq_array/ref_freq),ii+1)) # will be in seconds
        
        # get time shift based on the sample rate
        shift_dt = (1/signal._samprate).to('ms')
        shift_start = time.time()

        for ii, freq in enumerate(freq_array):
            signal._data[ii,:] = shift_t(signal._data[ii,:],
                                         time_delays[ii].value,
                                         dt=shift_dt.value)
            if (ii+1) % int(signal.Nchan//20) ==0:
                shift_check = time.time()
                percent = round((ii + 1)*100/signal.Nchan)
                elapsed = shift_check-shift_start
                chk_str = '\r{0:2.0f}% shifted'.format(percent)
                chk_str += ' in {0:4.3f} seconds.'.format(elapsed)

                try:
                    print(chk_str , end='', flush=True)
                #This is the Python 2 version
                #__future__ does not have 'flush' kwarg.
                except:
                    print(chk_str , end='')
                sys.stdout.flush()
        
        # May need to add tihs parameter to signal
        signal._FDshifted = True
    
    def scatter_broaden(self, signal, tau_d, ref_freq, beta = KOLMOGOROV_BETA, \
                        convolve = False, pulsar = None):
        """
        Function to add scatter broadening delays to simulated data. We offer
        two methods to do this, one where the delay is calcuated and the 
        pulse signals is directly shifted by the calculated delay (as done
        in the disperse function), or the scattering delay exponentials are 
        directy convolved with the pulse profiles. If this option is chosen, 
        the scatter broadening must be done BEFORE pulsar.make_pulses() is run.
        
        signal [object] : signal class object which has been previously defined
        tau_d [float] : scattering delay [seconds]
        ref_freq [float] : reference frequency [MHz] at which tau_d was measured
        beta [float] : preferred scaling law for tau_d, default is for a 
                       Kolmoogorov medium (11/3)
        convolve [bool] : If False, signal will be directly shifted in time by
                          scattering delay; if True, scattering delay tails
                          will be directly convolved with the pulse profiles.
        pulsar [object] : previously defined pulsar class object with profile
                          already assigned
        """
        # First get and define values to use
        freq_array = signal._dat_freq
        ref_freq = make_quant(ref_freq, 'MHz')
        tau_d = make_quant(tau_d, 's').to('ms') # need compatible units with dt
        # Scale the scattering timescale with frequency
        tau_d_scaled = self.scale_tau_d(tau_d, ref_freq , freq_array, beta=beta)
        # First shift signal if convolve = False
        if not convolve:
            # define bin size to shift by
            shift_dt = (1/signal._samprate).to('ms')
            shift_start = time.time()
            # now loop through and scale things appropriately
            for ii, freq in enumerate(freq_array):
                signal._data[ii,:] = shift_t(signal._data[ii,:],
                                             tau_d_scaled[ii].value,
                                             dt=shift_dt.value)
                if (ii+1) % int(signal.Nchan//20) ==0:
                    shift_check = time.time()
                    percent = round((ii + 1)*100/signal.Nchan)
                    elapsed = shift_check-shift_start
                    chk_str = '\r{0:2.0f}% scatter shifted'.format(percent)
                    chk_str += ' in {0:4.3f} seconds.'.format(elapsed)
    
                    try:
                        print(chk_str , end='', flush=True)
                    #This is the Python 2 version
                    #__future__ does not have 'flush' kwarg.
                    except:
                        print(chk_str , end='')
                    sys.stdout.flush()
        else:
            # Determine the exponential scattering tails
            """
            --> We need to figure out how the 2-D profiles will work and fit 
                in with the current data structure, such as in make_pulses()
                and init_data() because this convolution needs to happen
                before make pulses I think?
            """
            raise NotImplementedError()
        
    
    '''
    Written by Michael Lam, 2017
    Scale dnu_d and dt_d based on:
    dnu_d propto nu^(22/5)
    dt_d propto nu^(6/5) / transverse velocity
    See Stinebring and Condon 1990 for scalings with beta (they call it alpha)
    
    TODO: Should units be assigned here, or earlier?
    '''
    
    def scale_dnu_d(dnu_d,nu_i,nu_f,beta=KOLMOGOROV_BETA):
        """
        Scaling law for scintillation bandwidth as a function of frequency.
        dnu_d [float] : scintillation bandwidth [MHz]
        nu_i [float] : reference frequency at which du_d was measured [MHz]
        nu_f [float] : frequency (or frequency array) to scale dnu_d to [MHz]
        beta [float] : preferred scaling law for dnu_d, default is for a 
                       Kolmoogorov medium (11/3)
        """
        #dnu_d = make_quant(dnu_d, 'MHz')
        if beta < 4:
            exp = 2.0*beta/(beta-2) #(22.0/5)
        elif beta > 4:
            exp = 8.0/(6-beta)
        return dnu_d*(nu_f/nu_i)**exp
    
    def scale_dt_d(dt_d,nu_i,nu_f,beta=KOLMOGOROV_BETA):
        """
        Scaling law for scintillation timescale as a function of frequency.
        dt_d [float] : scintillation timescale [seconds]
        nu_i [float] : reference frequency at which du_d was measured [MHz]
        nu_f [float] : frequency (or frequency array) to scale dnu_d to [MHz]
        beta [float] : preferred scaling law for dt_d, default is for a 
                       Kolmoogorov medium (11/3)
        """
       # dt_d = make_quant(dt_d, 's')
        if beta < 4:
            exp = 2.0/(beta-2) #(6.0/5)
        elif beta > 4:
            exp = float(beta-2)/(6-beta)
        return dt_d*(nu_f/nu_i)**exp
    
    def scale_tau_d(tau_d,nu_i,nu_f,beta=KOLMOGOROV_BETA):
        """
        Scaling law for the scattering timescale as a function of frequency.
        tau_d [float] : scattering timescale [seconds?]
        nu_i [float] : reference frequency at which du_d was measured [MHz]
        nu_f [float] : frequency (or frequency array) to scale dnu_d to [MHz]
        beta [float] : preferred scaling law for tau_d, default is for a 
                       Kolmoogorov medium (11/3)
        """
        #tau_d = make_quant(tau_d, 's')
        if beta < 4:
            exp = -2.0*beta/(beta-2) #(-22.0/5)
        elif beta > 4:
            exp = -8.0/(6-beta)
        return tau_d*(nu_f/nu_i)**exp
    
    
