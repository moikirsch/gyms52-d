/**
 * Gyms +52: fichas sin ningún dato de contacto, horario, pases ni foto propia
 * quedan fuera del índice de Google (noindex, follow) y del sitemap de Yoast.
 * Siguen visibles en el sitio. En cuanto la ficha recibe un dato, vuelve a indexarse sola.
 */
if ( ! function_exists( 'g52_ficha_vacia' ) ) {
	function g52_ficha_vacia( $post_id ) {
		static $cache = array();
		$post_id = (int) $post_id;
		if ( $post_id <= 0 ) {
			return false;
		}
		if ( isset( $cache[ $post_id ] ) ) {
			return $cache[ $post_id ];
		}
		global $wpdb;
		$tabla = $wpdb->prefix . 'geodir_gd_place_detail';
		$fila  = $wpdb->get_row(
			$wpdb->prepare(
				"SELECT telefono, correo, sitio_web, instagram, facebook, tiktok, whatsapp, business_hours, pases, cadena, featured_image FROM {$tabla} WHERE post_id = %d",
				$post_id
			),
			ARRAY_A
		);
		if ( empty( $fila ) ) {
			return $cache[ $post_id ] = false;
		}
		foreach ( array( 'telefono', 'correo', 'sitio_web', 'instagram', 'facebook', 'tiktok', 'whatsapp', 'business_hours', 'pases', 'cadena' ) as $campo ) {
			if ( isset( $fila[ $campo ] ) && '' !== trim( (string) $fila[ $campo ] ) ) {
				return $cache[ $post_id ] = false;
			}
		}
		$foto = isset( $fila['featured_image'] ) ? (string) $fila['featured_image'] : '';
		if ( '' !== $foto && false === strpos( $foto, 'sin-foto' ) && false === strpos( $foto, 'placeholder' ) ) {
			return $cache[ $post_id ] = false;
		}
		return $cache[ $post_id ] = true;
	}
}

add_filter( 'wpseo_robots', function ( $robots ) {
	if ( is_singular( 'gd_place' ) && g52_ficha_vacia( get_queried_object_id() ) ) {
		return 'noindex, follow';
	}
	return $robots;
}, 20 );

add_filter( 'wpseo_sitemap_entry', function ( $url, $type, $post ) {
	if ( 'post' === $type && is_object( $post ) && isset( $post->post_type ) && 'gd_place' === $post->post_type && g52_ficha_vacia( $post->ID ) ) {
		return false;
	}
	return $url;
}, 10, 3 );
