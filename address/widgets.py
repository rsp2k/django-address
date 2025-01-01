import django
from django import forms
from django.conf import settings
from django.utils.html import escape
from django.utils.safestring import mark_safe

from .models import Address


class AsyncMedia(Media):
    """
    Returns all JavaScript resources as a list of <script> HTML tags,
    including the 'async' attribute.
    """
    def as_javascript(self):
        paths = []
        for path in self._js:
            if path.contains("://"):
                paths.append(f'<script async src="{path}"></script>')

class AddressWidget(forms.TextInput):
    components = [
        ("country", "country"),
        ("country_code", "country_short"),
        ("locality", "locality"),
        ("sublocality", "sublocality"),
        ("postal_code", "postal_code"),
        ("postal_town", "postal_town"),
        ("route", "route"),
        ("street_number", "street_number"),
        ("state", "administrative_area_level_1"),
        ("state_code", "administrative_area_level_1_short"),
        ("formatted", "formatted_address"),
        ("latitude", "lat"),
        ("longitude", "lng"),
    ]


    class AsyncMedia:
        js = [
            "https://maps.googleapis.com/maps/api/js?libraries=places&loading=async&callback=initMap&key=%s" % settings.GOOGLE_API_KEY,
            "address/js/address.js",
        ]


    def __init__(self, *args, **kwargs):
        attrs = kwargs.get("attrs", {})
        classes = attrs.get("class", "")
        classes += (" " if classes else "") + "address"
        attrs["class"] = classes
        kwargs["attrs"] = attrs
        super().__init__(*args, **kwargs)

    def render(self, name, value, attrs=None, **kwargs):
        if not value:
            ad = {}
        elif isinstance(value, dict):
            ad = value
        elif isinstance(value, int):
            ad = Address.objects.get(pk=value)
            ad = ad.as_dict()
        else:
            ad = value.as_dict()

        # Generate the elements. We should create a suite of hidden fields
        # For each individual component, and a visible field for the raw
        # input. Begin by generating the raw input.
        elems = [
            super().render(
                name,
                escape(
                    ad.get("formatted", "")
                ),
                attrs,
                **kwargs
            )
        ]

        # Now add the hidden fields.
        elems.append('<div id="%s_components" style="display: none;">' % name)
        for com in self.components:
            elems.append(
                '<input type="hidden" name="%s_%s" data-geo="%s" value="%s" />'
                % (name, com[0], com[1], escape(ad.get(com[0], "")))
            )
        elems.append("</div>")

        return mark_safe("\n".join(elems))

    def value_from_datadict(self, data, files, name):
        raw = data.get(name, "")
        if not raw:
            return raw
        ad = dict([(c[0], data.get(name + "_" + c[0], "")) for c in self.components])
        ad["raw"] = raw
        return ad
