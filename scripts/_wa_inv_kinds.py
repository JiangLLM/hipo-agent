# family -> kind, hand-coded from the intent templates + reference answers (see dump)
ADMIN = {
 279:'report-aggregate', 270:'report-aggregate', 285:'report-aggregate', 248:'report-aggregate',
 277:'report-aggregate', 1001:'report-aggregate',
 276:'rank-extrema', 366:'rank-extrema', 234:'rank-extrema',
 367:'arith-over-filtered', 1002:'arith-over-filtered',
 364:'record-lookup', 274:'record-lookup',
 250:'review-mining', 249:'review-mining', 245:'review-mining', 244:'review-mining', 288:'review-mining',
 368:'catalog-filter',
}
SHOP = {
 197:'arith-over-filtered', 162:'arith-over-filtered', 147:'arith-over-filtered', 160:'arith-over-filtered',
 213:'rank-extrema', 214:'rank-extrema', 193:'rank-extrema', 161:'rank-extrema',
 206:'record-lookup', 155:'record-lookup', 169:'record-lookup', 1355:'record-lookup',
 136:'review-mining', 222:'review-mining', 666:'review-mining', 1356:'review-mining',
 370:'catalog-search-extrema', 159:'catalog-search-extrema', 204:'catalog-search-extrema',
}
KIND = {'shopping_admin':ADMIN, 'shopping':SHOP}
# does the template's varying slot change the REQUESTED OUTPUT ATTRIBUTE (vs only a filter value)?
ATTR_SLOT = {'shopping_admin':{366,234,368,244,279}, 'shopping':{155,206}}
