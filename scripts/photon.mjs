const connection = process.env.PHOTON_CONNECTION || (process.env.SPECTRUM_PROJECT_ID ? 'spectrum' : 'beta')
if (connection === 'spectrum') await import('./spectrum.mjs')
else if (connection === 'beta') await import('./photon-beta.mjs')
else throw new Error('PHOTON_CONNECTION must be spectrum or beta')
