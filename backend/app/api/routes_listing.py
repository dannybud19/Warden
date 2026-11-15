"""Read a listing link before a case exists, to prefill the add-home form."""

from fastapi import APIRouter, Request

from app.aggregators.listing_reader.reader import read_listing, summary_message
from app.api.schemas import ListingPreview, ListingPreviewRequest

router = APIRouter()


@router.post("/listing/preview")
async def preview_listing(body: ListingPreviewRequest, request: Request) -> ListingPreview:
    """What the page at `url` states (address, rent, agency...). Never fails: a page that cannot
    be read gives a status and a message instead of an error, and nothing is stored."""
    details = await read_listing(body.url, request.app.state.service.ctx)
    return ListingPreview(
        **details.model_dump(include=set(ListingPreview.model_fields) - {"message"}),
        message=summary_message(details),
    )
