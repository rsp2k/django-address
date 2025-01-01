function initMap() {
  const inputs = document.querySelectorAll('input.address');
  if (inputs.length === 0) {
    console.warn('No elements with the class "address" found.');
    return;
  }

  inputs.forEach((input) => {
    const cmps = document.getElementById(`${input.name}_components`);
    const fmtd = document.querySelector(`input[name="${input.name}_formatted"]`);

    input.addEventListener('change', () => {
      if (input.value !== fmtd.value) {
        const cmpNames = [
          'country',
          'country_code',
          'locality',
          'postal_code',
          'postal_town',
          'route',
          'street_number',
          'state',
          'state_code',
          'formatted',
          'latitude',
          'longitude',
        ];

        const cachedFields = cmpNames.reduce((acc, name) => {
          const field = document.querySelector(`input[name="${input.name}_${name}"]`);
          acc[name] = field;
          return acc;
        }, {});

        Object.keys(cachedFields).forEach((name) => {
          const field = cachedFields[name];
          if (field) {
            field.value = '';
          } else {
            console.warn(`Field not found: ${input.name}_${name}`);
          }
        });
      }
    });

    try {
      const geocomplete = new google.maps.places.Autocomplete(input);
      geocomplete.addListener('place_changed', () => {
        const place = geocomplete.getPlace();
        if (!place.geometry) {
          console.error('Autocomplete returned no geometry');
          return;
        }

        if (fmtd) fmtd.value = input.value;

        if (cmps) {
          const components = {
            country: '',
            country_code: '',
            locality: '',
            postal_code: '',
            postal_town: '',
            route: '',
            street_number: '',
            state: '',
            state_code: '',
            formatted: '',
            latitude: place.geometry.location.lat(),
            longitude: place.geometry.location.lng(),
          };

          if (place.address_components) {
            place.address_components.forEach((component) => {
              component.types.forEach((type) => {
                if (components.hasOwnProperty(type)) {
                  components[type] = component.long_name;
                }
              });
            });
          }

          Object.keys(components).forEach((key) => {
            const field = cmps.querySelector(`[data-geo="${key}"]`);
            if (field) {
              field.value = components[key];
            } else {
              console.warn(`Field not found in components: ${key}`);
            }
          });
        }
      });
    } catch (error) {
      console.error('Google Maps API failed to initialize Autocomplete:', error);
    }
  });
}
