import logging

from django.conf import settings

from django.core.exceptions import ValidationError
from django.db import models

try:
    from django.db.models.fields.related_descriptors import ForwardManyToOneDescriptor
except ImportError:
    from django.db.models.fields.related import (
        ReverseSingleRelatedObjectDescriptor as ForwardManyToOneDescriptor,
    )

logger = logging.getLogger(__name__)

__all__ = ["Country", "State", "Locality", "Address", "AddressField"]


try:
    from timezonefinder import TimezoneFinder
    timezone_finder = TimezoneFinder()  # reuse

except ImportError:
    if settings.DEBUG:
        warnings.warn(f"django-address: pip install timezonefinder for Timezone Lookup Support")
    timezone_finder = None
    pass


class InconsistentDictError(Exception):
    pass


def _to_python(value):
    raw = value.get("raw", "")
    country = value.get("country", "")
    country_code = value.get("country_code", "")
    state = value.get("state", "")
    state_code = value.get("state_code", "")
    locality = value.get("locality", "")
    sublocality = value.get("sublocality", "")
    postal_town = value.get("postal_town", "")
    postal_code = value.get("postal_code", "")
    street_number = value.get("street_number", "")
    route = value.get("route", "")
    formatted = value.get("formatted", "")
    latitude = value.get("latitude", None)
    longitude = value.get("longitude", None)

    # If there is no value (empty raw) then return None.
    if not raw:
        return None

    # Fix issue with NYC boroughs (https://code.google.com/p/gmaps-api-issues/issues/detail?id=635)
    if not locality and sublocality:
        locality = sublocality

    # Fix issue with UK addresses with no locality
    # (https://github.com/furious-luke/django-address/issues/114)
    if not locality and postal_town:
        locality = postal_town

    # If we have an inconsistent set of value bail out now.
    if (country or state or locality) and not (country and state and locality):
        raise InconsistentDictError

    # Handle the country.
    try:
        country_obj = Country.objects.get(name=country)
    except Country.DoesNotExist:
        if country:
            if len(country_code) > Country._meta.get_field("code").max_length:
                if country_code != country:
                    raise ValueError("Invalid country code (too long): %s" % country_code)
                country_code = ""
            country_obj = Country.objects.create(name=country, code=country_code)
        else:
            country_obj = None

    # Handle the state.
    try:
        state_obj = State.objects.get(name=state, country=country_obj)
    except State.DoesNotExist:
        if state:
            if len(state_code) > State._meta.get_field("code").max_length:
                if state_code != state:
                    raise ValueError("Invalid state code (too long): %s" % state_code)
                state_code = ""
            state_obj = State.objects.create(name=state, code=state_code, country=country_obj)
        else:
            state_obj = None

    # Handle the locality.
    try:
        locality_obj = Locality.objects.get(name=locality, postal_code=postal_code, state=state_obj)
    except Locality.DoesNotExist:
        if locality:
            locality_obj = Locality.objects.create(name=locality, postal_code=postal_code, state=state_obj)
        else:
            locality_obj = None

    # Handle the address.
    try:
        if not (street_number or route or locality):
            address_obj = Address.objects.get(raw=raw)
        else:
            address_obj = Address.objects.get(street_number=street_number, route=route, locality=locality_obj)
    except Address.DoesNotExist:
        address_obj = Address(
            street_number=street_number,
            route=route,
            raw=raw,
            locality=locality_obj,
            formatted=formatted,
            latitude=latitude,
            longitude=longitude,
        )

        # If "formatted" is empty try to construct it from other values.
        if not address_obj.formatted:
            address_obj.formatted = str(address_obj)

        # Need to save.
        address_obj.save()

    # Done.
    return address_obj


##
# Convert a dictionary to an address.
##


def to_python(value):

    # Keep `None`s.
    if value is None:
        return None

    # Is it already an address object?
    if isinstance(value, Address):
        return value

    # If we have an integer, assume it is a model primary key.
    elif isinstance(value, int):
        return value

    # A string is considered a raw value.
    elif isinstance(value, str):
        obj = Address(raw=value)
        obj.save()
        return obj

    # A dictionary of named address components.
    elif isinstance(value, dict):

        # Attempt a conversion.
        try:
            return _to_python(value)
        except InconsistentDictError:
            return Address.objects.create(raw=value["raw"])

    # Not in any of the formats I recognise.
    raise ValidationError("Invalid address value.")


##
# A country.
##


class Country(models.Model):
    name = models.CharField(max_length=40, unique=True, blank=True)
    code = models.CharField(max_length=2, blank=True)  # not unique as there are duplicates (IT)

    class Meta:
        verbose_name_plural = "Countries"
        ordering = ("name",)

    def __str__(self):
        return "%s" % (self.name or self.code)


##
# A state. Google refers to this as `administration_level_1`.
##


class State(models.Model):
    name = models.CharField(max_length=165, blank=True)
    code = models.CharField(max_length=8, blank=True)
    country = models.ForeignKey(Country, on_delete=models.CASCADE, related_name="states")

    class Meta:
        unique_together = ("name", "country")
        ordering = ("country", "name")

    def __str__(self):
        txt = self.to_str()
        country = "%s" % self.country
        if country and txt:
            txt += ", "
        txt += country
        return txt

    def to_str(self):
        return "%s" % (self.name or self.code)


##
# A locality (suburb).
##


class Locality(models.Model):
    name = models.CharField(max_length=165, blank=True)
    postal_code = models.CharField(max_length=10, blank=True)
    state = models.ForeignKey(State, on_delete=models.CASCADE, related_name="localities")

    class Meta:
        verbose_name_plural = "Localities"
        unique_together = ("name", "postal_code", "state")
        ordering = ("state", "name")

    def __str__(self):
        txt = "%s" % self.name
        state = self.state.to_str() if self.state else ""
        if txt and state:
            txt += ", "
        txt += state
        if self.postal_code:
            txt += " %s" % self.postal_code
        cntry = "%s" % (self.state.country if self.state and self.state.country else "")
        if cntry:
            txt += ", %s" % cntry
        return txt



class UsCensusBureauAddressManagerGeoCoderMixin(models.Manager):
    def geocode(self, address_string):
        """
        Geocodes/Creates a US address using the US Census Bureau's API.
        Args:
            address_string (str): The address to geocode.
        Returns:
            tuple: A tuple containing (latitude, longitude) if successful,
                   otherwise None.
        """

        cached_reply = UsCensusBureauCache.objects.check_cache(
            address_string=address_string,
        )
        if cached_reply:
            return cached_reply

        url = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
        params = {
            "address": address_string,
            "benchmark": "Public_AR_Current", # Use current benchmark
            "format": "json"
        }
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            json_response = response.json()


            """        
            print(response.text)

            result = {
                "input": {
                    "address": {
                        "address":"4179 N. Marcliffe Ave, Boise, ID"
                    },
                    "benchmark": {
                        "isDefault":true,
                        "benchmarkDescription":"Public Address Ranges - Current Benchmark",
                        "id":"4",
                        "benchmarkName":"Public_AR_Current"}
                },
                "addressMatches":[
                    { 
                        "tigerLine": {
                            "side":"R",
                            "tigerLineId":"117869523"
                        },
                        "coordinates": {
                            "x":-116.308812139437,
                            "y":43.643163617594
                        },
                        "addressComponents": {
                            "zip":"83704",
                            "streetName":"MARCLIFFE",
                            "preType":"",
                            "city":"BOISE",
                            "preDirection":"N",
                            "suffixDirection":"",
                            "fromAddress":"4299",
                            "state":"ID",
                            "suffixType":"AVE",
                            "toAddress":"4101",
                            "suffixQualifier":"",
                            "preQualifier":""
                        },
                        "matchedAddress":" 4179 N MARCLIFFE AVE, BOISE, ID, 83704"
                    }
                ]
            }
            """

        except requests.exceptions.RequestException as e:
            print(f"Error connecting to the Census Bureau API: {e}")
            return None

        try:
            if 'addressMatches' not in json_response:
                return None

            elif len(json_response['address_matches']) > 1:
                return json_response['address_matches']

            else:
                result = json_response['address_matches'][0]

            latitude = result["coordinates"]["y"]
            longitude = result["coordinates"]["x"]
            matched_address = result["matchedAddress"]
    #        tiger_line = result["tigerLine"]

            zip_code = result["addressComponents"]["zip"]
            city = result["addressComponents"]["city"]
            state = result["addressComponents"]["state"]
            # score = result["score"]
            # match_type = result["matchType"]
            # result["addressComponents"]["preType"]
            # result["addressComponents"]["preDirection"]
            # result["addressComponents"]["suffixDirection"]
            # result["addressComponents"]["fromAddress"]
            # result["addressComponents"]["suffixType"]
            # result["addressComponents"]["toAddress"]
            # result["addressComponents"]["suffixQualifier"]
            # result["addressComponents"]["preQualifier"]
            # result["addressComponents"] = {
            #     "zip":"83704",
            #     "streetName":"MARCLIFFE",
            #     "preType":"",
            #     "city":"BOISE",
            #     "preDirection":"N",
            #     "suffixDirection":"",
            #     "fromAddress":"4299",
            #     "state":"ID",
            #     "suffixType":"AVE",
            #     "toAddress":"4101",
            #     "suffixQualifier":"",
            #     "preQualifier":""
            # },

            geographies = result["geographies"]
            country_name = None
            if "County" in geographies:
                county_data = geographies["County"][0]  # Access the first county
                county_geoid = county_data["GEOID"]
                county_name = county_data["NAME"]
    #            print(f"County GEOID: {county_geoid}, County Name: {county_name}")
    #        else:
    #            print("County information not available.")
            # Print census tract information (if available)
            tract_geoid = None
            if "Tract" in geographies:  # Use 'Tract' instead of 'Census Tract'
                tract_data = geographies["Tract"][0]
                tract_geoid = tract_data["GEOID"]
                tract_name = tract_data["NAME"]
    #            print(f"Tract GEOID: {tract_geoid}, Tract Name: {tract_name}")
    #        else:
    #            print("Census Tract information not available.")

            address_obj, created = Address.objects.get_or_create(
                formatted=matched_address,
                latitude=latitude,
                longitude=longitude,
                city=city,
                state=state,
                postal_code=zip_code,
                defaults={
                    'raw' :address_string,
                    'country': country_name,
                    'census_data': result,
                }
            )

            UsCensusBureauCache.objects.create(
                address_obj=address_obj,
                address_string=self,
            )

            return address_obj

        except (KeyError, TypeError) as e:
            print(f"Error parsing the Census Bureau API response: {e}")
            return None


class AddressManager(UsCensusBureauAddressGeoCoderManagerMixin):
    # Add the UsCensusBureau GeoCoder
    pass


class UsCensusBureauCacheQuerySet(models.QuerySet):
    MAX_AGE_DAYS = 100
    def valid(self):
        return self.filter(
            created_at__gte=timezone.now() - timedelta(days=self.MAX_AGE_DAYS),
        )
    def check_cache(self, address_string):
        try:
            return self.valid().get(
                address_string=address_string,
            )

        except self.model.DoesNotExist:
            return self.model.objects.none()

    def clear_cache(self, max_days_old=self.MAX_AGE_DAYS):
        return self.filter(
            created_at__lte=timezone.now() - timedelta(days=max_days_old)
        ).delete()


class UsCensusBureauCache(models.Model):
    objects = UsCensusBureauCacheQuerySet.as_manager()
    address_string = models.CharField(max_length=120, db_index=True)
    matched_address = models.ForeignKey("Address", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    data = models.JSONField(
        help_text="Data retrieved from US Census API",
        default=dict(),
    )

    @property
    def tiger_line(self):
        return self.data.get("tigerLine", None)

    @property
    def address_components(self):
        return self.data.get('addressComponents', None)

##
# An address. If for any reason we are unable to find a matching
# decomposed address we will store the raw address string in `raw`.
##

class Address(models.Model):
    objects = AddressManager()
    street_number = models.CharField(max_length=20, blank=True)
    route = models.CharField(max_length=100, blank=True)
    locality = models.ForeignKey(
        Locality,
        on_delete=models.CASCADE,
        related_name="addresses",
        blank=True,
        null=True,
    )
    raw = models.CharField(max_length=200)
    formatted = models.CharField(max_length=200, blank=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)

    class Meta:
        verbose_name_plural = "Addresses"
        ordering = ("locality", "route", "street_number")

    @property
    def timezone(self):
        """
        Support lat/lon based Timezone Lookup if timezonefinder is installed
        """
        if not timezone_finder:
            warnings.warn(f"django-address: tried to call Address.timezone, but timezonefinder isn't available! `pip install timezonefinder`")
            return None

        if not (self.latitude and self.longitude):
            # Todo, geocode if necessary, this is edge case
            # if self.formatted:
            #     address = self.formatted
            # elif self.raw:
            #     address = self.raw
            # else:
            #     raise ValueError("Can't get timezone for {self} when no lat/lon/formatted/raw is set!")

            # Geocode address to lat/log
            #lat, long = geocode(address)
            raise ValueError("Can't get timezone for {self} when no lat/lon/formatted/raw is set!")

        return timezone_finder.timezone_at(
            lng=self.longitude, lat=self.latitude
        )

    def __str__(self):
        if self.formatted != "":
            txt = str(self.formatted)
        elif self.locality:
            txt = ""
            if self.street_number:
                txt = str(self.street_number)
            if self.route:
                if txt:
                    txt += str(self.route)
            locality = str(self.locality)
            if txt and locality:
                txt += ", "
            txt += locality
        else:
            txt = str(self.raw)
        return txt

    def clean(self):
        if not self.raw:
            raise ValidationError("Addresses may not have a blank `raw` field.")

    def as_dict(self):
        ad = dict(
            street_number=self.street_number,
            route=self.route,
            raw=self.raw,
            formatted=self.formatted,
            latitude=self.latitude if self.latitude else "",
            longitude=self.longitude if self.longitude else "",
        )
        if self.locality:
            ad["locality"] = self.locality.name
            ad["postal_code"] = self.locality.postal_code
            if self.locality.state:
                ad["state"] = self.locality.state.name
                ad["state_code"] = self.locality.state.code
                if self.locality.state.country:
                    ad["country"] = self.locality.state.country.name
                    ad["country_code"] = self.locality.state.country.code
        return ad


class AddressDescriptor(ForwardManyToOneDescriptor):
    def __set__(self, inst, value):
        super(AddressDescriptor, self).__set__(inst, to_python(value))


##
# A field for addresses in other models.
##


class AddressField(models.ForeignKey):
    description = "An address"

    def __init__(self, *args, **kwargs):
        kwargs["to"] = "address.Address"
        # The address should be set to null when deleted if the relationship could be null
        default_on_delete = models.SET_NULL if kwargs.get("null", False) else models.CASCADE
        kwargs["on_delete"] = kwargs.get("on_delete", default_on_delete)
        super(AddressField, self).__init__(*args, **kwargs)

    def contribute_to_class(self, cls, name, virtual_only=False):
        from address.compat import compat_contribute_to_class

        compat_contribute_to_class(self, cls, name, virtual_only)

        setattr(cls, self.name, AddressDescriptor(self))

    def formfield(self, **kwargs):
        from .forms import AddressField as AddressFormField

        defaults = dict(form_class=AddressFormField)
        defaults.update(kwargs)
        return super(AddressField, self).formfield(**defaults)
